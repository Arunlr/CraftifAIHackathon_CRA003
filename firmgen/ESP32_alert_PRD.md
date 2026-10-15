# PRD - Vision Alert Actuator (ESP32) for a PipeGen closed loop

**Version:** 1.0  **Board:** ESP32-WROOM-32 DevKit (DevKitC / DevKit V1)  **Framework:** ESP-IDF v5.5
**Use:** Upload this file to FirmGen ("PRD-driven build"), review the generated requirements, freeze them,
then build, flash and run the acceptance tests below on the real board.

## 1. Purpose
A PC runs a PipeGen-generated NVIDIA DeepStream perception pipeline plus `action_engine.py`. When a
perception rule fires (elephant on track, hand in press die zone, wrong-way vehicle...), the PC sends a
command over USB serial. This firmware turns that command into a physical action (siren, lights,
relay, barrier servo) in under 50 ms, and fails safe if the PC link is lost.

## 2. Hardware and pin map
| Function | GPIO | Notes |
|---|---|---|
| Buzzer (active 5 V buzzer through NPN transistor) | 25 | HIGH = sound |
| Red LED (220 ohm) | 26 | critical / link lost |
| Amber LED (220 ohm) | 27 | warning |
| Green LED (220 ohm) | 14 | all clear |
| Relay module IN (active HIGH) | 33 | HIGH = machine / gate ENABLED |
| Servo signal (SG90, optional) | 13 | 50 Hz LEDC PWM; 0 deg = barrier closed, 90 deg = open |
| On-board LED | 2 | heartbeat |

## 3. Interface - UART0 over USB, 115200 baud, 8N1, ASCII lines terminated by `\n` (accept `\r\n`)
| Command from PC | Meaning | Board reply |
|---|---|---|
| `PING` | keep-alive, sent every 1 s when there is no alert | `PONG` |
| `ALERT <level> <tag>` | level 2 = warning, 3 = critical; tag up to 32 chars; re-sent every 1 s while active | `OK ALERT <level>` |
| `CLEAR` (optional tag) | back to all clear | `OK CLEAR` |
| `STATUS` | report state | `STATE level=<n> link=<ok/lost> uptime_ms=<n>` |
| anything else | invalid | `ERR unknown_command` |

## 4. Functional requirements
- **FR1** State machine with states CLEAR (0), WARNING (2), CRITICAL (3), LINK_LOST.
- **FR2** CLEAR: green LED on, amber/red off, buzzer off, relay HIGH (enabled), servo 90 deg.
- **FR3** WARNING: amber LED blinks at 2 Hz, buzzer beeps 100 ms once per second, relay HIGH.
- **FR4** CRITICAL: red LED solid, buzzer continuous, relay LOW (machine blocked), servo 0 deg.
- **FR5** LINK_LOST (fail-safe): if no valid command arrives for 3 s, red LED blinks at 4 Hz, buzzer off,
  relay LOW, servo 0 deg. The next valid command moves to the state it implies (`PING` -> CLEAR,
  `ALERT n` -> level n).
- **FR6** Every state change prints exactly one line: `STATE level=<n> tag=<tag> t=<ms>`.
- **FR7** Heartbeat: on-board LED toggles every 500 ms while the firmware runs.
- **FR8** Line parser handles partial reads, CRLF and lines up to 64 bytes; longer lines -> `ERR too_long`;
  the parser never blocks the output task or crashes.
- **FR9** At boot print `READY vision-alert-actuator v1.0` and enter CLEAR.

## 5. Non-functional requirements
- **NFR1** Command-to-GPIO latency of 50 ms or less (last byte received -> output pin change).
- **NFR2** No dynamic allocation in the command path; UART handled by a dedicated FreeRTOS task with an
  event queue; task watchdog enabled.
- **NFR3** Boot to CLEAR within 2 s of reset.

## 6. Acceptance criteria (verify on the board with the serial monitor)
- **AC1** After reset: `READY ...` printed, green LED on, relay HIGH within 2 s.
- **AC2** Send `PING` -> `PONG` within 20 ms.
- **AC3** Send `ALERT 3 test` -> red LED + continuous buzzer, relay LOW, servo 0 deg, `STATE level=3` line,
  all within 50 ms.
- **AC4** Send `ALERT 2 test` -> amber LED blinking at 2 Hz (+/-10%) and one beep per second.
- **AC5** Send `CLEAR` -> green LED, buzzer off, relay HIGH, `STATE level=0` line.
- **AC6** Send nothing for 3 s -> LINK_LOST behaviour (FR5); then `PING` -> CLEAR.
- **AC7** Send `HELLO` -> `ERR unknown_command`; send a 100-byte line -> `ERR too_long`; firmware keeps running.
- **AC8** Heartbeat LED blinks at 1 Hz (+/-10%) throughout all tests.

## 7. Integration with the PipeGen side
`action_engine.py` with this in the config:
```yaml
sinks:
  serial: {enabled: true, port: COM3, baud: 115200}   # Windows COM port of the ESP32 (Device Manager)
```
It sends `ALERT <level> <rule>` / `CLEAR` on every actuator change and repeats the current state every
second. Run the engine on **Windows Python** when using serial (WSL2 cannot see COM ports without usbipd);
it can still subscribe to PipeGen's MQTT broker inside WSL at `mqtt://localhost:1883/#`.
