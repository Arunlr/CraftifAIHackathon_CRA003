# PipeGen Wildcard Playbook: HackwithBangalore 4.0 (ASUS TUF A15)

> **Deadline: Thu 15 Oct 2026, 11:00 PM IST.** (The email also says "10 PM PST", which is ~10:30 AM IST on
> 16 Oct. Plan for **11 PM IST** and confirm on Discord.) Submit by **10:30 PM** at the latest.

> **Update 19:15 IST: about 3 h 45 min left.** Follow the compressed plan in **section 6**. New in the kit:
> `configs/zebra_guard.yaml` (pedestrian safety, closed-loop friendly) and `configs/shwana_suraksha.yaml`
> (stray dogs at school gates), with simulator scenarios `zebra` and `dogs` and a new `zone_conflict` rule.

---

## Format and tools (checked 19:23 IST)
- **Tonight is remote.** Build on your own laptop and submit online by 11 PM IST. Only the **top 20** go in person
  to the finale: HackwithBangalore 4.0, **30 Oct 2026, Microsoft office Bengaluru**, an offline 8-hour event where
  you bring your own laptop ([Devnovate](https://devnovate.co/event/hack-with-bangalore-40)).
- The Luma link is CraftifAI's **Embedded SF** hackathon (in person in San Francisco, already over). You quote it
  because the wildcard uses its problem statement. Its "live demo at the venue" step can't happen tonight, so a
  **demo video is essential**.
- **Required:** a CraftifAI account (sign in *before* building; free, 3M credits on first sign-in:
  https://developer.craftifai.com/dashboard?tab=downloads) + **PipeGen v0.5.1**, all 5 stages.
- **Optional:** FirmGen v0.4.1 + a real ESP32 (Closed Loop bonus) · Edge MLOps (train your own model; skip tonight).
  Not relevant: AgentIQ (FPGA), Live Intelligence (FirmGen-track bonus).
- **Form:** the problem statement's PipeGen form is https://forms.gle/eJyeCKCG2UH757QZ8 (written for the SF event).
  Use the link in your wildcard email if it has one; otherwise confirm on Discord that wildcard entries go there.

## 0. Do these 3 things right now (before reading the rest)
1. **Start the PipeGen download and install** (section 2). The first launch pulls a ~12 GB DeepStream image. Let it
   run while you plan.
2. **Join the CraftifAI Discord** (link on developer.craftifai.com). Ask in #community-support for the wildcard
   **submission form** and confirm the deadline.
3. **Download 2–3 test videos** for your idea (section 6), as H.264 MP4 at 720p or 1080p.

---

## 1. Your laptop: verdict
ASUS TUF A15 with a 6-core Ryzen 5 (4600H / 7535HS) ships with an **NVIDIA GTX 1650, RTX 2050 or RTX 3050 (4 GB)**,
usually **8 GB RAM** and a 512 GB SSD ([ASUS spec](https://www.asus.com/ca-en/laptops/for-gaming/tuf-gaming/2021-asus-tuf-gaming-a15/techspec/)).
**PipeGen needs the NVIDIA GPU, not the CPU. You can do this track.**

| Constraint | What it means for you |
|---|---|
| 4 GB VRAM | Use **YOLOv8n/s**, **1–2 streams**, 720p/1080p. Skip BEV fusion / heavy multi-model stacks |
| 8 GB RAM | Give WSL 6 GB plus 16 GB swap (below). Close Chrome and games while TensorRT builds engines |
| Windows laptop | Use **WSL2** (PipeGen supports it: Windows driver **560.76+**, **30 GB** free) ([PipeGen page](https://developer.craftifai.com/products/pipegen)) |
| Built-in webcam | **Not visible inside WSL2**. Use a **video file** (allowed by the rules) or your phone as an RTSP camera |
| Power | **Plug in the charger.** On battery the GPU is throttled and your FPS/power report looks bad |

**Windows settings (2 min):** Armoury Crate, then **GPU Mode = Standard or Ultimate (NOT Eco**: Eco switches the
NVIDIA GPU off), then Operating Mode = **Performance/Turbo**. Update the driver via the NVIDIA App, then run
`nvidia-smi` in PowerShell. It must show the GPU and driver ≥ 560.76.

---

## 2. Install PipeGen on WSL2 (≈ 30–60 min, mostly download)
PowerShell **as Administrator**:
```powershell
wsl --install -d Ubuntu-22.04        # reboot if asked, create a Linux user
wsl --update
notepad $env:USERPROFILE\.wslconfig  # paste the 3 lines below, save
wsl --shutdown
```
```ini
[wsl2]
memory=6GB      # 12GB if your laptop has 16 GB RAM
swap=16GB
```
In **Ubuntu**:
```bash
nvidia-smi                 # GPU visible? (never install a Linux NVIDIA driver inside WSL)
echo $DISPLAY              # should print :0  (WSLg provides the GUI PipeGen needs)
df -h ~                    # 30 GB+ free
mkdir -p ~/videos ~/pg && cd ~/pg
cp /mnt/c/Users/<YOU>/Downloads/pipegen_prerequisites_*.sh /mnt/c/Users/<YOU>/Downloads/PipeGen_0.5.1_amd64.deb .
chmod +x pipegen_prerequisites_*.sh && ./pipegen_prerequisites_*.sh   # Docker + NVIDIA Container Toolkit (5–10 min)
```
Then `wsl --shutdown` in PowerShell, reopen Ubuntu (this applies the docker group), and continue:
```bash
cd ~/pg && sudo apt install ./PipeGen_0.5.1_amd64.deb
pipegen --version          # must print 0.5.1
pipegen                    # first launch downloads ~12 GB; if it drops, run again (resumes)
sudo apt install -y mosquitto mosquitto-clients python3-pip
pip3 install paho-mqtt pyyaml
```
> If the **WSL2 tab** on the PipeGen download page uses different file names or steps, follow that tab; it is the
> source of truth. If you have **Docker Desktop**, quit it first (it can clash with the Docker the script installs).
> **Dual-boot Ubuntu instead?** Log in with "Ubuntu on Xorg"; PipeGen refuses to start on Wayland.

**If WSL2 breaks** (first four from NVIDIA's [DeepStream-on-WSL FAQ](https://docs.nvidia.com/metropolis/deepstream/dev-guide/text/DS_WSL2_FAQ.html)):
- `could not select device driver "" with capabilities: [[gpu]]`: run
  `sudo apt install --reinstall nvidia-container-toolkit && sudo service docker restart`, then `wsl --shutdown` and reopen.
- `GPU access blocked by the operating system`: not every GPU/driver combo works in WSL. Check that GPU mode is not
  Eco, update the Windows driver, and see NVIDIA's WSL constraints page.
- Pipeline runs but the video window is black (`Failed to attach to x11 shm`): pick **file output** and play the MP4.
  MQTT output keeps working, so the action layer is unaffected.
- `Error while setting IOCTL` / `S_EXT_CTRLS for CUDA_GPU_ID failed` and then a crash: the container can't see
  `/usr/lib/wsl/lib/libnvcuvid.so.1` and `libnvidia-encode.so.1`. Post the log on the PipeGen Discord immediately.
- PipeGen says Wayland is not supported: try `env -u WAYLAND_DISPLAY pipegen` (WSLg still provides X11 on `:0`).

---

## 3. What exactly you build, and with what
```
 test video (MP4) / phone RTSP
        |
 [1] PipeGen  -> Requirement -> Pipeline IR -> Model (YOLOv8 COCO) -> Compiler (TensorRT FP16, then INT8) -> Run
        |        generates a DeepStream C/C++ app + run.sh: decode (NVDEC) -> nvinfer -> nvtracker -> OSD
        +--> annotated video window / RTSP          (demo)
        +--> MQTT or JSON metadata  ---------------> [2] action_engine.py (this kit): zones, dwell, wrong-way...
                                                         +--> [3] dashboard.py      (live KPIs + event feed)
                                                         +--> [4] Telegram alert    (phone notification)
                                                         +--> [5] ESP32 via FirmGen (optional closed-loop bonus)
```

| # | Piece | Use | You do | Time |
|---|---|---|---|---|
| 1 | **Perception app** | **PipeGen v0.5.1** (DeepStream 7.1 + TensorRT) | Write the requirement, confirm the PIR, pick the COCO model, compile FP16 + INT8, run on your video with MQTT/JSON output | 1.5 h |
| 2 | Message bus | **Mosquitto** (in WSL) | `sudo apt install mosquitto` | 5 min |
| 3 | Action layer | **`action_engine.py` + a config** (this kit) | Draw zones with `zone_picker.html`, set stream size and labels | 30 min |
| 4 | Dashboard | **`dashboard.py`** | Fill the `perf:` block with PipeGen's numbers | 5 min |
| 5 | Phone alerts | **Telegram Bot API** | @BotFather, then set the token + chat id | 10 min |
| 6 | Evidence | PipeGen screenshots | PIR node graph + TensorRT speed report (FP16 vs INT8) | 10 min |
| 7 | Demo video | **OBS Studio** or Win+G (Xbox Game Bar) | 2-minute recording (script in section 9) | 30 min |
| 8 | Repo | **GitHub** | PipeGen export folder + kit + README + evidence | 20 min |
| 9 | *(optional)* Physical action | **ESP32 + buzzer/LED/relay + FirmGen (runs on Windows x64)** ([FirmGen](https://developer.craftifai.com/products/firmgen)) | Upload `firmgen/ESP32_alert_PRD.md`, flash, set `serial` in the config | 1 h |

**Why this scores:** the rules demand all 5 PipeGen stages, a TensorRT engine with a speed report, a live run, and an
*actionable* output, with PipeGen **load-bearing** ([track doc](https://docs.google.com/document/d/1nxSV7QiLeO3DvOLIdt2AOiZQtMqIYqt5m2tSAqqwmAY/edit)).
In this design every detection comes from the PipeGen app; the kit only *acts* on PipeGen's metadata.

---

## 4. Idea bank (★ = ready config in this kit, ⚡ = closed-loop bonus friendly)

### Tier A: COCO classes or pose only. No training. Buildable today on a 4 GB laptop GPU
| # | Idea | PipeGen sees | Rule (kit) | Actionable output |
|---|---|---|---|---|
| 1 | ★ **Gaja-Rakshak**: elephant early warning on rail tracks | elephant, person (COCO) | zone_enter + zone_dwell + line_cross | "STOP trains" alert to loco pilot / forest guard, safe-crossing counter |
| 2 | ★ **Namma Traffic Sentinel**: triple riding + wrong-way + bus lane + footpath | motorcycle, person, car, bus, truck | group_on_vehicle, wrong_way, zone_dwell, zone_enter | violation log, violations per hour |
| 3 | ★ **Bheed-Kavach**: crowd-crush early warning at gates | person | count_threshold + line_cross + wrong_way (counter-flow) | GREEN/AMBER/RED, "hold Gate 3" advice |
| 4 | ★ **ParkSense**: hospital/apartment parking + fire lane | car | slot_occupancy + zone_dwell | free-slot count, "LOT FULL", fire-lane alert |
| 5 | ★ **Unattended Bag Sentinel**: metro or railway concourse | suitcase, backpack, handbag + person | unattended | security dispatch alert |
| 6 | ★ **SafeNest**: fall alert for elders living alone (JSON only) | person | fall | family alert, no video leaves the device |
| 7 | ★⚡ **Kavach-Press**: hand-in-die interlock for power presses | person **pose** (wrists) | danger_zone | ESP32 relay blocks the stroke, buzzer |
| 8 | BMTC bus-stop demand sensor | person | count_threshold (≥ N for 5 min) | "send an extra bus" to the depot dashboard |
| 9 | Lake Guard: debris-dumping trucks at night | truck | zone_dwell (60 s at the lake edge) | snapshot alert to a lake-warden group |
| 10 | Level-crossing guardian | car, motorcycle, person, cow | zone_dwell (inside crossing) | alert to station master / loco pilot |
| 11 | ⚡ Highway cattle warning | cow | zone_enter (carriageway) | ESP32 flashing "CATTLE AHEAD" sign |
| 12 | School-van "No child left behind" | person (cabin cam) | count_threshold ≥ 1 after the trip | call to driver + school |
| 13 | Library / canteen seat finder | chair, person, backpack | slot_occupancy + unattended (seat hogging) | live free-seat map |
| 14 | Restaurant table turnover | person, dining table | slot_occupancy | "table 4 free / needs cleaning" |
| 15 | Hospital bed-exit watch (prevent the fall) | person | zone_enter (bed-edge or floor zone) | nurse alert before the fall |
| 16 | ⚡ EscaGuard: person down on escalator | person | fall | ESP32 relay = emergency stop |
| 17 | Stray-dog census for the ABC programme | dog | line_cross / count | per-ward counts for sterilisation planning |
| 18 | ⚡ Phone-while-driving monitor | cell phone + person (driver zone) | zone_dwell | ESP32 buzzer in the cabin |
| 19 | ★⚡ **Zebra-Guard**: did the vehicle yield at the zebra crossing? | person, car, motorcycle, bus, truck | count_threshold + **zone_conflict** + line_cross | amber "STOP, PEDESTRIANS" sign while people cross; red + buzzer + evidence log for each no-yield |
| 20 | ★⚡ **Shwana-Suraksha**: stray-dog pack at a school gate at dismissal | dog, person | count_threshold + **zone_conflict** + line_cross | guard/headmaster alert, siren for a pack, per-gate dog log for the ABC programme |

### Fresh batch (added 19:15): more Tier-A ideas, with how much extra work each needs
| Idea | PipeGen sees | Extra work tonight | Actionable output |
|---|---|---|---|
| ⚡ **Signal-Saathi**: adaptive signal timing from live queue counts | car, motorcycle, bus, truck per approach zone | new `adaptive_signal` rule + ESP32 traffic-light PRD (~45 min) | green-time split per approach, LEDs on an ESP32 "junction" |
| **BMTC Stop-Skip**: bus passes the stop without stopping while people wait | bus, person | config-only reuse of `zone_conflict` (classes bus, protected person); tune `seconds` | timestamped complaint log for BMTC |
| **Queue-ETA**: live wait time at OPD / RTO / Passport Seva / temple queues | person | new `queue_eta` rule (~20 min) | "Wait ≈ 18 min" board, open-another-counter alert |
| **Raksha-Signal**: SOS gesture (both hands above head for 3 s) at bus shelters / ATMs | person **pose** | new `pose_gesture` rule (~20 min); you can film yourself | police / guardian alert with camera id |
| ⚡ **Urja-Saver**: lights and fans follow occupancy in classrooms / offices | person | PRD tweak: relay follows occupancy (~10 min) | relay on/off + kWh-saved estimate |
| ⚡ **Footboard-Kavach**: person hanging on the bus footboard while moving | person (door camera) | zone_dwell config; footage is the hard part | buzzer for the driver |
| **Gully-Umpire** (fun): front-foot no-ball call | person **pose** (ankles) + crease line | new rule + timing (~40 min) | "NO BALL" buzzer |

### Tier B: needs a ready ONNX from PipeGen **Deep Search** (give it max 15 min, else fall back to Tier A)
Helmetless riders · fire & smoke (warehouses, forest edges) · potholes from dashcam (GPS-tagged for BBMP) ·
garbage black spots · PPE (helmet/vest) on construction sites · crop-raiding wild boar / monkeys ⚡ (strobe + siren).

### Why the top picks are strong (facts for your pitch)
- **Elephants:** Tamil Nadu's Madukkarai AI system (12 towers, 24 thermal cameras) has enabled **6,592 safe
  crossings with zero elephant deaths since Nov 2023** ([ABP](https://news.abplive.com/news/india/ai-warning-system-helps-elephants-cross-railway-track-safely-tamil-nadu-govt-shares-video-madukkarai-1794381)).
  Your pitch: the same idea as one low-power edge box per hotspot.
- **Traffic:** Bengaluru logged **79,545 triple-riding cases in the first 151 days of 2026 (527/day)**
  ([Bangalore Mirror](https://bangaloremirror.indiatimes.com/bangalore/cover-story/triple-whammy/articleshow/131730569.cms)) and
  **1.78 lakh wrong-way cases in Q1 2026**, a five-year high ([The Hindu](https://www.pressreader.com/india/the-hindu-bangalore-9ww1/20260427/281582362227086)).
- **Crowds:** 11 people died in the stampede outside Chinnaswamy Stadium on 4 June 2025
  ([New Indian Express](https://www.newindianexpress.com/cities/bengaluru/2025/Jun/04/rcb-victory-celebrations-turn-tragic-as-11-die-in-stampede-at-chinnaswamy-stadium)).
- **Power presses:** **875** auto-sector workers assisted by Safe in India reported crush injuries (lost fingers) in
  2024; two-thirds happened on machines like power presses ([Indian Express](https://indianexpress.com/article/business/workers-in-automotive-industry-face-safety-risk-as-injuries-rise-35-per-cent-yoy-safe-in-india-foundation-report-10135876/)).
- **Pedestrians (Zebra-Guard):** **136 pedestrians killed and 664 injured** on Bengaluru roads in Jan–Jun 2026
  ([Siasat](https://www.siasat.com/136-pedestrians-killed-664-hurt-between-jan-june-in-bengaluru-3503287/)); about **28%** of the city's
  road deaths are pedestrians ([TOI](https://timesofindia.indiatimes.com/city/bengaluru/over-200-pedestrian-deaths-in-bengaluru-each-year-walkers-make-up-28-of-total-road-deaths/articleshow/125886289.cms)).
- **Stray dogs (Shwana-Suraksha):** **18,140 dog-bite cases** under the GBA in the first five months of 2026, up 55%
  year on year, rising especially among children and the elderly ([Deccan Herald](https://www.deccanherald.com/india/karnataka/bengaluru/dog-bites-in-bengaluru-surge-55-year-on-year-4043025)).
- **Signals (Signal-Saathi):** the city's adaptive system BATCS runs at **169 junctions** and cut travel time by
  **15–20%**, while Bengaluru is still the world's 3rd-most congested city ([AIM](https://analyticsindiamag.com/ai-features/how-ai-traffic-management-systems-are-redefining-indias-smart-cities));
  the city has **40,000+ intersections** ([TOI](https://timesofindia.indiatimes.com/city/bengaluru/bengaluru-to-get-ai-driven-traffic-system-at-165-junctions-by-january-2025/articleshow/114096352.cms)).

**My recommendation:** **#1 Gaja-Rakshak** (most distinctive, lowest risk). **#2 Traffic Sentinel** (most technical
depth). **#7 Kavach-Press** only if you already own an ESP32 and want the closed-loop bonus.
**#19 Zebra-Guard** is the best new pick: simple to explain, footage is easy to find, and it maps onto the ESP32 PRD
as-is (amber = people crossing, red + buzzer = no-yield).

---

## 5. Build cards (top 3 + the 2 new ready configs)

### #1 Gaja-Rakshak (config: `configs/elephant_track.yaml`, simulator: `elephant`)
- **PipeGen requirement (paste into stage 1):**
  *"Real-time elephant and person detection with tracking for a camera beside a railway track. Input: video file
  (later RTSP). Publish per-frame object metadata (class, track id, bounding box) over MQTT to localhost:1883 and save
  an annotated video. Target: NVIDIA RTX laptop GPU, TensorRT FP16, then INT8."*
- **Model stage:** pick the catalog YOLOv8 detector and confirm it is **COCO-80** (has `elephant`). If it isn't,
  use Deep Search for "yolov8 coco onnx".
- **Video:** Pexels / Pixabay: "elephants crossing road", "elephant herd walking". Daylight, side view.
- **Rules:** approach zone (warning), track zone dwell ≥ 2 s (critical), person on track, crossing counter.
- **Bonus story:** a solar-powered pole box needs few watts, so the INT8 vs FP16 power column justifies INT8.
- **Be honest about limits:** night needs thermal (that is what Madukkarai uses). Next step: fine-tune on thermal
  footage with Edge MLOps.

### #2 Namma Traffic Sentinel (config: `configs/traffic_sentinel.yaml`, simulator: `traffic`)
- **Requirement:** *"Real-time vehicle and person detection with multi-object tracking for a traffic junction camera;
  classes car, motorcycle, bus, truck, bicycle, person; publish per-frame metadata with track IDs over MQTT; annotated
  RTSP output."*
- **Video:** Pexels "india traffic", "motorcycle traffic". Elevated angle, so lanes are visible.
- **Rules:** wrong-way (direction arrow along the lanes), triple riding (3+ persons on one motorcycle box), bus lane
  dwell ≥ 3 s, footpath entry, vehicle counter.
- **Wow line:** "Four violation types from one COCO model, zero custom training, on a 4 GB laptop GPU."
- **Limit:** triple riding under heavy occlusion undercounts; helmets would need a Deep Search model (v2).

### #3 Kavach-Press ⚡ (config: `configs/kavach_press.yaml`, simulator: `press`)
- **Requirement:** *"Real-time human pose estimation (17 keypoints) for a camera above a machine work area; publish
  keypoints and boxes over MQTT."*
- **Demo rig:** phone (IP Webcam app, RTSP) looking at a desk "press" (stapler or paper cutter). The ESP32 relay/servo
  is the press enable. A hand in the die zone gives BLOCKED + buzzer; clear for 1 s and it is enabled again.
- **FirmGen:** upload `firmgen/ESP32_alert_PRD.md`, freeze requirements, flash, run AC1–AC8, export the traceability report.
- **Wiring the loop:** run `action_engine.py` with **Windows Python** (COM port), subscribed to the WSL Mosquitto
  at `mqtt://localhost:1883/#`.

### #4 Zebra-Guard ⚡ (config: `configs/zebra_guard.yaml`, simulator: `zebra`)
- **Requirement:** *"Real-time detection and multi-object tracking of pedestrians and vehicles (person, car,
  motorcycle, bus, truck, bicycle) for a camera overlooking a zebra crossing. Input: video file. Publish per-frame
  object metadata with track IDs and bounding boxes over MQTT to localhost:1883 and save an annotated video. Target:
  NVIDIA laptop GPU, TensorRT FP16, then INT8."*
- **Video:** search "zebra crossing pedestrians cars India", "pedestrian crossing traffic". Elevated, fixed camera;
  the whole crossing visible.
- **Rules:** people on the crosswalk (warning, drives the amber sign), `zone_conflict` = vehicle still **moving**
  inside the crosswalk while ≥ 1 person is on it (critical), pedestrians-served and vehicles-passed counters.
  A vehicle that stops and waits is *not* flagged.
- **Wow line:** "Every no-yield is logged with time, class and track id, and the sign warns drivers before anyone
  is hit."
- **Limit:** a pedestrian hidden behind a bus is missed; a second camera angle fixes that.

### #5 Shwana-Suraksha ⚡ (config: `configs/shwana_suraksha.yaml`, simulator: `dogs`)
- **Requirement:** *"Real-time detection and tracking of dogs and people for a camera at a school gate. Input: video
  file. Publish per-frame object metadata with track IDs over MQTT to localhost:1883. TensorRT FP16, then INT8."*
- **Video:** search "stray dogs street India", "street dogs pack". Any clip with dogs and people works for the demo.
- **Rules:** 2 dogs at the gate = warning, 3+ = critical (pack); a dog among ≥ 2 children for 3 s = warning
  (`zone_conflict` with `min_movement: 0`); dog arrivals and departures per gate.
- **Be careful in the pitch:** the output is "send the guard / call the ABC team", never anything that harms animals.

---

## 6. Timeline for tonight (IST), compressed at 19:15
| Time | Do | Done when |
|---|---|---|
| **19:15 – 19:30** | `nvidia-smi` in PowerShell (GPU model + driver), GPU mode Standard/Ultimate, charger in. **Pick the idea now** (default: Gaja-Rakshak) | GPU listed, idea fixed |
| **19:30 – 20:15** | WSL2 + PipeGen install (section 2) with the ~12 GB pull running. *Meanwhile:* download 2 clips, run the kit demo with the simulator, make the Telegram bot | `pipegen` opens |
| **20:15 – 21:15** | PipeGen: Requirement, PIR, Model, Compiler (**FP16 engine + speed report**), Run on your clip with MQTT. Then `--print-raw 3`, fix `stream` size and labels, draw zones on *your* clip | Alerts fire on the real video |
| **21:15 – 21:35** | *Only if on schedule:* **INT8 compile** + FP16 vs INT8 table. Otherwise skip, and say "INT8 is next" | `perf:` filled |
| **21:35 – 22:15** | Screenshots (PIR graph, speed report), record the 2-min demo (section 9), README, push the repo | Repo public, video uploaded |
| **22:15 – 22:30** | **Submit.** Check every link in an incognito window | Confirmation received |

**Cut-offs:** if PipeGen is not running by **20:30**, post your exact error on the PipeGen Discord and ask about a
cloud GPU. If it is still blocked at **21:30**, submit what you have (PipeGen screenshots + kit demo + honest status):
a partial entry beats a missed deadline.

Convert YouTube/WebM clips to something DeepStream can decode:
`ffmpeg -i in.webm -c:v libx264 -preset fast -crf 23 -an ~/videos/clip.mp4`

---

## 7. Evidence and submission checklist
- [ ] Screenshot: **Pipeline IR node graph**
- [ ] Screenshot: **TensorRT speed report** (FP16, plus INT8 for the bonus)
- [ ] Live run recorded: PipeGen window + dashboard + phone alert (+ ESP32 if closed loop)
- [ ] `mosquitto_sub` output saved to `evidence/mqtt_messages.txt` (proves the actionable feed)
- [ ] Repo contains the **PipeGen export folder** (run.sh, configs, generated sources)
- [ ] Project description: problem, Track A pipeline (**inputs, tasks, models, precision, outputs**), bonus claimed
- [ ] (Closed loop) FirmGen **traceability report** + UART log of the acceptance tests

**Repo layout**
```
gaja-rakshak/
  pipegen_export/      <- the files PipeGen generated (run.sh, DeepStream configs, C/C++ sources, build/speed logs)
  action/              <- this kit (action_engine.py, dashboard.py, configs/elephant_track.yaml)
  evidence/            <- pir_graph.png, trt_fp16.png, trt_int8.png, dashboard.png, mqtt_messages.txt
  README.md            <- template below
```
(GitHub rejects files > 100 MB; leave big videos out and link them instead.)

---

## 8. README template for your submission
```markdown
# Gaja-Rakshak: Edge AI elephant early warning for railway tracks
**Track A: PipeGen** · Bonus: Edge Optimization (INT8) [+ Closed Loop if built]

## Problem
Elephants are killed on railway tracks; Madukkarai (TN) proved AI early warning works. We make it a low-power edge box.

## PipeGen pipeline
| Stage | Ours |
|---|---|
| Input | 1080p H.264 video file (RTSP-ready) |
| Tasks | detection + multi-object tracking |
| Model | YOLOv8s COCO-80 (catalog) -> TensorRT FP16 and INT8 |
| Outputs | MQTT per-frame metadata, annotated video, alerts (Telegram, dashboard) |

## Results (from PipeGen's reports, RTX 3050 Laptop 4 GB)
| Precision | FPS | Latency (ms) | Power (W) | Accuracy |
|---|---|---|---|---|
| FP16 | | | | |
| INT8 | | | | |

## Architecture
PipeGen DeepStream app -> MQTT -> action engine (zones/dwell/crossings) -> dashboard + Telegram (+ ESP32 siren)

## Evidence
PIR graph, speed reports, MQTT log, demo video link

## Run
bash pipegen_export/run.sh ; python action/action_engine.py -c action/configs/elephant_track.yaml --source "mqtt://localhost:1883/#" ; python action/dashboard.py
```

---

## 9. The 2-minute demo video
| Time | Show | Say |
|---|---|---|
| 0:00–0:15 | Title + one stat | "6,592 safe elephant crossings in Madukkarai prove early warning works. We built it as an edge box." |
| 0:15–0:40 | PipeGen: requirement, **PIR graph**, model, **speed report** | "PipeGen turned one sentence into a TensorRT DeepStream pipeline." |
| 0:40–1:25 | Split screen: annotated video + dashboard; alert fires; phone buzzes | "Elephant enters the track zone, critical alert in under a second, only JSON leaves the device." |
| 1:25–1:45 | FP16 vs INT8 table | "INT8 gives X FPS at Y W with Z accuracy, so it fits a solar pole unit or a Jetson Orin Nano." |
| 1:45–2:00 | Roadmap | "Next: thermal camera for night, multi-camera per GPU, Jetson deployment." |

---

## 10. Judge Q&A prep
- **"Is PipeGen load-bearing?"** All perception (decode, TensorRT inference, tracking, metadata) is the
  PipeGen-generated DeepStream app. Without it the system sees nothing; the engine only acts on its output.
- **"What about night?"** Thermal or IR camera, with a fine-tuned model via Deep Search or Edge MLOps. Same pipeline.
- **"False alarms?"** Two-stage alerts (approach, then on-track), dwell timers, confidence thresholds, zone design.
- **"Why edge, not cloud?"** No connectivity in forests and on highways; latency; privacy (only JSON leaves); cost.
- **"INT8 accuracy drop?"** Point to PipeGen's accuracy column; keep FP16 where the drop is unacceptable.
- **"How does it scale?"** DeepStream batches many streams per GPU; one Jetson per pole for remote sites.
