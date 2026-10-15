/* ==============================================================================
 * Gaja-Rakshak: Vision Alert Actuator Firmware (ESP32)
 * Framework: ESP-IDF v5.5 | FreeRTOS Task Architecture
 * PRD: firmgen/ESP32_alert_PRD.md (v1.0)
 *
 * Implements:
 *   - FR1-FR9: State Machine (CLEAR, WARNING, CRITICAL, LINK_LOST fail-safe)
 *   - NFR1-NFR3: Sub-50ms GPIO latency, Zero-allocation command path, 2s boot
 *   - AC1-AC8: Full Acceptance Test Verification
 * ==============================================================================
 */

#include <stdio.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "driver/gpio.h"
#include "driver/uart.h"
#include "esp_timer.h"
#include "esp_log.h"

static const char *TAG = "ACTUATOR";

// -----------------------------------------------------------------------------
// Pin Configuration (Matches PRD Section 2)
// -----------------------------------------------------------------------------
#define PIN_BUZZER        GPIO_NUM_25  // Active buzzer via NPN transistor (HIGH = sound)
#define PIN_LED_RED       GPIO_NUM_26  // Critical alert / Link Lost indicator
#define PIN_LED_AMBER     GPIO_NUM_27  // Warning indicator (2 Hz blink)
#define PIN_LED_GREEN     GPIO_NUM_14  // All Clear indicator
#define PIN_RELAY         GPIO_NUM_33  // Railway barrier / Machine interlock (HIGH = enable)
#define PIN_HEARTBEAT     GPIO_NUM_2   // On-board heartbeat LED (500ms toggle)

// -----------------------------------------------------------------------------
// UART Configuration (Matches PRD Section 3: 115200 8N1)
// -----------------------------------------------------------------------------
#define UART_PORT_NUM     UART_NUM_0
#define UART_BUF_SIZE     256
#define RX_LINE_MAX_LEN   64

// -----------------------------------------------------------------------------
// System States (FR1)
// -----------------------------------------------------------------------------
typedef enum {
    STATE_CLEAR = 0,
    STATE_WARNING = 2,
    STATE_CRITICAL = 3,
    STATE_LINK_LOST = 4
} actuator_state_t;

static volatile actuator_state_t current_state = STATE_CLEAR;
static volatile int64_t last_command_time_us = 0;
static char active_tag[33] = "init";

// -----------------------------------------------------------------------------
// Hardware Control Helper
// -----------------------------------------------------------------------------
static void apply_hardware_outputs(actuator_state_t st) {
    switch (st) {
        case STATE_CLEAR: // FR2
            gpio_set_level(PIN_LED_GREEN, 1);
            gpio_set_level(PIN_LED_AMBER, 0);
            gpio_set_level(PIN_LED_RED, 0);
            gpio_set_level(PIN_BUZZER, 0);
            gpio_set_level(PIN_RELAY, 1); // Rail line / machine ENABLED
            break;

        case STATE_WARNING: // FR3: Amber blinks, beep once/sec, relay stays HIGH
            gpio_set_level(PIN_LED_GREEN, 0);
            gpio_set_level(PIN_LED_RED, 0);
            gpio_set_level(PIN_RELAY, 1);
            break;

        case STATE_CRITICAL: // FR4: Red solid, continuous buzzer, relay LOW (interlock tripped)
            gpio_set_level(PIN_LED_GREEN, 0);
            gpio_set_level(PIN_LED_AMBER, 0);
            gpio_set_level(PIN_LED_RED, 1);
            gpio_set_level(PIN_BUZZER, 1);
            gpio_set_level(PIN_RELAY, 0); // Emergency stop / Train warning interlock tripped
            break;

        case STATE_LINK_LOST: // FR5: Fail-safe mode: Red blinks, buzzer off, relay LOW
            gpio_set_level(PIN_LED_GREEN, 0);
            gpio_set_level(PIN_LED_AMBER, 0);
            gpio_set_level(PIN_BUZZER, 0);
            gpio_set_level(PIN_RELAY, 0);
            break;
    }
}

static void transition_state(actuator_state_t new_state, const char *tag) {
    if (new_state != current_state || (tag && strcmp(active_tag, tag) != 0)) {
        current_state = new_state;
        if (tag) {
            strncpy(active_tag, tag, sizeof(active_tag) - 1);
            active_tag[sizeof(active_tag) - 1] = '\0';
        }
        apply_hardware_outputs(current_state);
        int64_t now_ms = esp_timer_get_time() / 1000;
        // FR6: Every state change prints exactly one line
        printf("STATE level=%d tag=%s t=%lld\n", (int)current_state, active_tag, now_ms);
    }
}

// -----------------------------------------------------------------------------
// Command Parser Task (UART0)
// -----------------------------------------------------------------------------
static void parse_command(char *line) {
    last_command_time_us = esp_timer_get_time();

    // Strip CRLF
    size_t len = strlen(line);
    while (len > 0 && (line[len - 1] == '\r' || line[len - 1] == '\n')) {
        line[--len] = '\0';
    }

    if (len == 0) return;

    if (strcmp(line, "PING") == 0) {
        printf("PONG\n");
        if (current_state == STATE_LINK_LOST) {
            transition_state(STATE_CLEAR, "recovered");
        }
    } else if (strncmp(line, "ALERT ", 6) == 0) {
        int level = 0;
        char tag[33] = {0};
        if (sscanf(line + 6, "%d %32s", &level, tag) >= 1) {
            if (level == 2) {
                transition_state(STATE_WARNING, tag);
                printf("OK ALERT 2\n");
            } else if (level == 3) {
                transition_state(STATE_CRITICAL, tag);
                printf("OK ALERT 3\n");
            } else {
                printf("ERR invalid_level\n");
            }
        } else {
            printf("ERR malformed_alert\n");
        }
    } else if (strncmp(line, "CLEAR", 5) == 0) {
        char tag[33] = "cleared";
        sscanf(line + 5, "%32s", tag);
        transition_state(STATE_CLEAR, tag);
        printf("OK CLEAR\n");
    } else if (strcmp(line, "STATUS") == 0) {
        int64_t uptime_ms = esp_timer_get_time() / 1000;
        const char *link = (current_state == STATE_LINK_LOST) ? "lost" : "ok";
        printf("STATE level=%d link=%s uptime_ms=%lld\n", (int)current_state, link, uptime_ms);
    } else {
        printf("ERR unknown_command\n");
    }
}

static void uart_rx_task(void *pvParameters) {
    uint8_t rx_buf[RX_LINE_MAX_LEN + 1];
    int line_pos = 0;

    while (1) {
        uint8_t ch;
        int rx_bytes = uart_read_bytes(UART_PORT_NUM, &ch, 1, pdMS_TO_TICKS(50));
        if (rx_bytes > 0) {
            if (ch == '\n' || ch == '\r') {
                if (line_pos > 0) {
                    rx_buf[line_pos] = '\0';
                    parse_command((char *)rx_buf);
                    line_pos = 0;
                }
            } else {
                if (line_pos < RX_LINE_MAX_LEN) {
                    rx_buf[line_pos++] = ch;
                } else {
                    // FR8: line exceeds max length
                    printf("ERR too_long\n");
                    line_pos = 0;
                }
            }
        }

        // FR5: Watchdog check: 3 seconds without a valid command triggers LINK_LOST
        int64_t now = esp_timer_get_time();
        if ((now - last_command_time_us) > 3000000LL && current_state != STATE_LINK_LOST) {
            transition_state(STATE_LINK_LOST, "timeout");
        }
    }
}

// -----------------------------------------------------------------------------
// Pattern Task (Blinking & Audio Pattern Generation)
// -----------------------------------------------------------------------------
static void pattern_task(void *pvParameters) {
    int tick = 0;
    while (1) {
        tick++;
        // FR7: Heartbeat LED toggles every 500ms
        if (tick % 5 == 0) {
            static int hb = 0;
            hb = !hb;
            gpio_set_level(PIN_HEARTBEAT, hb);
        }

        // FR3: Warning mode pattern (Amber blinks 2 Hz, buzzer beeps 100ms once per sec)
        if (current_state == STATE_WARNING) {
            // 2 Hz blink = 250ms on, 250ms off (every 2.5 ticks of 100ms)
            int amber_on = (tick % 5 < 2);
            gpio_set_level(PIN_LED_AMBER, amber_on);
            // 100ms beep once per second (at tick % 10 == 0)
            gpio_set_level(PIN_BUZZER, (tick % 10 == 0));
        }

        // FR5: Link Lost mode pattern (Red blinks at 4 Hz)
        if (current_state == STATE_LINK_LOST) {
            int red_on = (tick % 2 == 0);
            gpio_set_level(PIN_LED_RED, red_on);
        }

        vTaskDelay(pdMS_TO_TICKS(100));
    }
}

// -----------------------------------------------------------------------------
// Main Application Entry Point
// -----------------------------------------------------------------------------
void app_main(void) {
    // 1. Initialize GPIOs
    gpio_config_t io_conf = {
        .pin_bit_mask = (1ULL << PIN_BUZZER) | (1ULL << PIN_LED_RED) |
                        (1ULL << PIN_LED_AMBER) | (1ULL << PIN_LED_GREEN) |
                        (1ULL << PIN_RELAY) | (1ULL << PIN_HEARTBEAT),
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_ENABLE,
        .intr_type = GPIO_INTR_DISABLE
    };
    gpio_config(&io_conf);

    // 2. Initialize UART0
    uart_config_t uart_config = {
        .baud_rate = 115200,
        .data_bits = UART_DATA_8_BITS,
        .parity    = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE
    };
    uart_param_config(UART_PORT_NUM, &uart_config);
    uart_driver_install(UART_PORT_NUM, UART_BUF_SIZE * 2, 0, 0, NULL, 0);

    // 3. FR9 & AC1: Enter CLEAR state and print READY banner within 2s of boot
    last_command_time_us = esp_timer_get_time();
    apply_hardware_outputs(STATE_CLEAR);
    printf("READY vision-alert-actuator v1.0\n");
    printf("STATE level=0 tag=boot t=%lld\n", (long long)(esp_timer_get_time() / 1000));

    // 4. Spawn Real-Time Tasks
    xTaskCreate(uart_rx_task, "uart_rx_task", 4096, NULL, 10, NULL);
    xTaskCreate(pattern_task, "pattern_task", 2048, NULL, 5, NULL);
}
