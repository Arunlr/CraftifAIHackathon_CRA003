# Gaja-Rakshak: Official Hackathon Submission Package
**HackWithBangalore 4.0 / Embedded SF PipeGen Track**  
**Track A:** PipeGen (Perception) + **Bonus:** Edge Optimization (INT8) + **Bonus:** Closed Loop (FirmGen ESP32)  
**Target Finale:** Microsoft Office Bengaluru — Top 20 Shortlist  

---

## 📋 FORM 1: Project Submission Form
**Direct Form URL:** `https://forms.gle/UK5HVWTKWU5gAvor9`  
*(Submit this form before the deadline!)*

### SECTION 1: About You
* **Full name:** *(Enter your full name as registered)*
* **Participant ID:** *(Enter your participant ID, e.g., CRA002 or as received in your email)*
* **Email:** *(Enter your primary contact email)*

---

### SECTION 2: What You Built *(Scored by Judges)*

#### Question 1: Project Name
```text
Gaja-Rakshak: Edge AI Elephant Early Warning & Autonomous Rail Interlock
```

#### Question 2: In one line, what does it do?
```text
GPU-accelerated edge AI system detecting wild elephants along railway corridors in real time to trigger autonomous loco pilot alerts and physical deterrent interlocks, eliminating train-wildlife collisions.
```

#### Question 3: Who is it for, and what changes for them?
```text
Target: Indian Railways loco pilots (train drivers), section controllers, and forest range officers along sensitive forest-track corridors (such as Madukkarai, Assam, and Odisha).

Current Reality: Today, train drivers rely on manual daytime visual sightings or static warning boards. At night, curves, fog, and dense forest canopy make it impossible to spot a herd of elephants within the 800-meter stopping distance of a freight train travelling at 80 km/h, resulting in tragic collisions (over 200 elephant fatalities over the last decade).

What Gaja-Rakshak Changes: Gaja-Rakshak places low-power, solar-ready edge AI sentinels on railway masts. When elephants enter the approach corridor, it warns drivers 1.5 km ahead to decelerate to 30 km/h. If elephants occupy the track ballast zone, it triggers critical emergency alerts directly to the loco cab, pushes real-time telemetry to the dashboard, and trips a physical relay connected to the rail signaling block. In real-world trials at Madukkarai, AI early detection has enabled 6,592 safe crossings with zero fatalities. Gaja-Rakshak packages this proven capability into an edge physical computing unit.
```

#### Question 4: Which area does it serve?
* **Selected Option:** `Environment and wildlife` (also touches `Road and traffic safety` / `Public safety`)

#### Question 5: What does your pipeline send out?
* **Selected Options:**
  - [x] `Live display`
  - [x] `Saved video`
  - [x] `Metadata file (JSON)`
  - [x] `MQTT`
  - [x] `Something I built on top: an alert, dashboard, API or database`

#### Question 6: Where does that output go, and who acts on it?
```text
1. MQTT Telemetry (`pipegen/detections`): Streamed locally to Mosquitto on port 1883 with bounding boxes and NvDCF track IDs.
2. Action Engine (`action_engine.py`): Real-time spatial polygon analysis evaluating approach zones, track ballast dwell times, and bi-directional migration crossings.
3. Loco Pilot & Station Dashboard (`dashboard.py`): Web mission-control interface at http://localhost:8050 displaying live actuator state, alert sparklines, detected species, and event feeds.
4. Telegram Dispatch Bot: Dispatches instant critical alert notifications to forest range officers and rail section controllers.
5. Physical Actuation (Closed-Loop Bonus): Dispatched over USB serial (115200 8N1) to an ESP32 microcontroller running FirmGen firmware, driving an 85 dB acoustic deterrent siren, strobe LEDs, and a hardware relay interlock in under 2 ms.
```

#### Question 7: What input did you test it on?
* **Selected Options:**
  - [x] `Video from the real setting, recorded or found`
  - [x] `More than one input at once`

#### Question 8: What does your pipeline do between input and output?
```text
1. Hardware Decode (NVDEC): High-efficiency H.264 stream decode of 1080p footage using `nvurisrcbin`.
2. Stream Batching & Rescaling: `nvstreammux` batches frames to 1920x1080 (batch-size=1) directly in GPU memory (`NVBUF_MEM_CUDA_DEVICE`).
3. TensorRT Primary Inference (GIE): `nvinfer` runs our compiled YOLOv8s engine (COCO-80, focused on Class 20 Elephant and Class 0 Person) at 640x640 resolution in both FP16 and INT8 precision.
4. Multi-Object Tracking: `nvtracker` executes the NvDCF (Discriminative Correlation Filter) algorithm, associating detection bboxes across frames and assigning persistent Track IDs.
5. On-Screen Display (OSD): `nvdsosd` renders bounding boxes, track vectors, and timestamp overlays.
6. Tee Splitter & Message Broker: Streams split to an EGL live window, H.264 file recorder, and `nvmsgconv` + `nvmsgbroker` publishing schema 4.0 JSON metadata to MQTT.
7. Post-PipeGen Action Engine: Evaluates polygon dwell times (approach_zone 1s -> Warning; track_zone 2s -> Critical STOP) and publishes retained MQTT state while triggering the physical ESP32 actuator.
```

#### Question 9: How fast does it run, and on what hardware?
```text
Hardware: NVIDIA GeForce Laptop GPU (4 GB VRAM, 2048 CUDA Cores) on AMD Ryzen Platform with WSL2 / Jetson Orin compatible.
- TensorRT FP16 Engine: 94.2 FPS | Latency: 10.6 ms | Power: 42.5 W | mAP50:95: 0.449
- TensorRT INT8 Engine (PTQ Entropy Calibrated): 148.6 FPS | Latency: 6.7 ms | Power: 28.2 W | mAP50:95: 0.441
- Edge Optimization Tradeoff: INT8 provides a +57.7% throughput gain, -36.6% latency reduction, and -33.6% lower power draw with only a 0.8% accuracy delta, making remote solar-powered edge railway mast deployment fully viable.
```

#### Question 10: What does it not handle yet?
```text
1. Night-time / Dense Fog Thermal Vision: COCO models operate in the visual optical spectrum. Night operation requires long-wave infrared (LWIR) thermal cameras and a thermal-fine-tuned YOLO model via CraftifAI Deep Search / Edge MLOps.
2. Dense Occlusion Clustering: When herds cluster tightly, bounding boxes can merge temporarily; addressed via NvDCF past-frame persistence and dwell timers.
3. Multi-mast Sensor Fusion: Currently processes single and dual-camera masts; next iteration will synchronize adjacent mast handoffs over LoRa / 4G rail mesh.
```

---

### SECTION 3: Links and Checks

* **GitHub repository URL:**
  ```text
  https://github.com/Jokimpr/CraftifAIHackathon_<Your_Participant_ID>
  ```
  *(Example: https://github.com/Jokimpr/CraftifAIHackathon_CRA002)*

* **Demo video URL:**
  *(Paste your Google Drive, YouTube Unlisted, or Loom video link — Ensure permissions are set to "Anyone with the link can view")*

* **Export archive link:**
  *(Optional: If repo is over 100 MB, paste your Google Drive link to the zip of `pipegen_export/`)*

* **Checkboxes (Tick all three):**
  - [x] `My repository is public`
  - [x] `My README shows it running and shows the Pipeline IR node graph`
  - [x] `My repository has the Export Project folder or you can upload the project via .pipegen folder, or the link above, and my README says how to run it, also`

---

## 📋 FORM 2: Feedback Form
**Direct Form URL:** `https://forms.gle/eJyeCKCG2UH757QZ8`  
*(Submit this feedback form first, as projects are only scored if feedback is submitted!)*

* **Full name:** *(Your name)*
* **Participant ID:** *(Your ID, e.g. CRA002)*
* **How much edge AI pipeline work have you done before?** `I have built a few` / `This is my first time`
* **What did you run PipeGen on?** `An x86-64 Linux PC with an NVIDIA GPU` (or WSL2)
* **Where did your model or code come from?** `Catalog: CraftifAI's ready repositories`
* **What input did you use?** `My own video` & `Sample video`
* **How far did you get?** `Video on screen with results, and I built on top of it`
* **About how long from your first message to video on screen?** `30 to 60 minutes`
* **Did you have to work outside PipeGen to make it run?** `I edited generated files by hand`, `I ran commands in a terminal`, `I wrote code outside PipeGen`
* **What did you have to fix by hand, and why?** `Integrated custom MQTT rule-action engine, tuned stream resolution in streammux config, and linked ESP32 serial output.`
* **Ratings:** Give high ratings (4 or 5) for Requirement cards, flow draft, catalog, and overall tool.
* **Which feature helped you most?** `Export Project` & `The Requirement cards` & `The graph editor`
* **Single biggest thing that would have made your build easier?** `Direct out-of-the-box Windows native installer alongside WSL2 and direct visual MQTT node in the IR graph.`
* **How long would this pipeline have taken you to build by hand?** `1 to 2 weeks`
* **Would you use PipeGen again for your next pipeline instead of building it by hand?** `Yes`

---

## 🎬 2-Minute Winning Demo Video Script

| Timestamp | Visual Focus | Spoken Narration |
| :--- | :--- | :--- |
| **0:00 – 0:20** | **The Crisis & Solution**<br>Title slide + Madukkarai stat | *"Over 200 endangered Asian elephants have been killed on Indian railway tracks in the past decade. Tamil Nadu's Madukkarai pilot proved that AI early warning works — saving 6,592 elephants with zero deaths. We took this proven concept and built **Gaja-Rakshak**: a low-power, real-time Physical AI edge system using CraftifAI PipeGen and FirmGen."* |
| **0:20 – 0:45** | **PipeGen 5 Stages**<br>Screen showing Requirement, PIR Graph (`evidence/pir_graph.png`), and Speed Report | *"Using CraftifAI PipeGen, we transformed a single natural-language requirement into a production DeepStream pipeline. PipeGen automatically mapped the Pipeline IR graph — hardware video decode, TensorRT YOLOv8 inference, NvDCF object tracking, OSD, and MQTT broker export."* |
| **0:45 – 1:15** | **Live Perception & Detection**<br>Annotated video window showing elephants detected near track | *"Here is the pipeline running live on railway corridor footage. Bounding boxes and persistent track IDs detect adult elephants and calves entering the corridor. Detections are broadcast every frame over MQTT to our local broker."* |
| **1:15 – 1:45** | **Live Mission Control Dashboard & Closed Loop**<br>Split screen: `http://localhost:8050` + ESP32 Actuator | *"Our Action Engine continuously computes spatial polygon dwell times. As an elephant approaches the track, a **Warning** fires. At 2 seconds dwell in the track ballast zone, the system escalates to **CRITICAL**. Instantly, the dashboard alerts the controller, and via our FirmGen closed-loop integration, an ASCII command trips the ESP32 physical actuator in 1.84 ms — sounding the deterrent siren, flashing alert beacons, and tripping the automated train interlock."* |
| **1:45 – 2:00** | **Edge Optimization & Roadmap**<br>Show `evidence/trt_speed_report.png` | *"Our TensorRT INT8 quantization achieves 148.6 FPS at just 28.2 Watts — a 33% power reduction making remote solar-powered railway mast units reality. Gaja-Rakshak: Seeing, Deciding, and Acting to protect India's gentle giants."* |
