# GStreamer Setup for KLV Muxing

## Why GStreamer?

FFmpeg cannot properly mux raw KLV data streams into MPEG-TS without PES wrapping. GStreamer's `mpegtsmux` has better support for custom data streams and metadata.

## Required Packages

Install GStreamer and required plugins:

```bash
sudo apt-get update
sudo apt-get install -y \
    gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad \
    gstreamer1.0-plugins-ugly \
    gstreamer1.0-libav \
    gstreamer1.0-tools \
    gstreamer1.0-rtsp
```

## Verify Installation

Check that `mpegtsmux` is available:

```bash
gst-inspect-1.0 mpegtsmux
```

Check that `srtsink` is available:

```bash
gst-inspect-1.0 srtsink
```

If `srtsink` is missing, install:

```bash
sudo apt-get install -y gstreamer1.0-plugins-bad-apps
```

## Switch to GStreamer

To use GStreamer instead of FFmpeg:

```bash
# Backup current video.py
cp parrot_forwarder/video.py parrot_forwarder/video_ffmpeg.py

# Use GStreamer version
cp parrot_forwarder/video_gstreamer.py parrot_forwarder/video.py

# Restart service
sudo systemctl restart parrot_forwarder
```

## Test GStreamer Pipeline Manually

Test if GStreamer can read the drone's RTSP stream:

```bash
gst-launch-1.0 rtspsrc location=rtsp://192.168.53.1/live protocols=udp ! \
    rtph264depay ! h264parse ! fakesink -v
```

Test if GStreamer can read the KLV TS stream:

```bash
gst-launch-1.0 udpsrc port=12345 ! tsparse ! fakesink -v
```

## Troubleshooting

### Missing mpegtsmux

If `mpegtsmux` is not found:
```bash
sudo apt-get install -y gstreamer1.0-plugins-bad
```

### Missing srtsink

If `srtsink` is not found:
```bash
# Build from source or use alternative output
# Fallback: Use udpsink instead of srtsink
```

### Pipeline Errors

Check GStreamer logs:
```bash
GST_DEBUG=3 gst-launch-1.0 [your-pipeline]
```

## Alternative: Use udpsink Instead of srtsink

If SRT is not available in GStreamer, use UDP output and FFmpeg for SRT:

```python
# GStreamer pipeline outputs to UDP
pipeline = "... ! mpegtsmux ! udpsink host=127.0.0.1 port=5000"

# Separate FFmpeg process reads UDP and outputs to SRT
ffmpeg -f mpegts -i udp://127.0.0.1:5000 -c copy -f mpegts srt://0.0.0.0:8890?mode=listener
```

