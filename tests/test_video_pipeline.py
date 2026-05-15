from parrot_forwarder.video import VideoForwarder


def test_srt_pipelines_resend_h264_headers_for_late_joiners() -> None:
    forwarder = VideoForwarder("192.168.53.1", srt_port=8890, klv_port=12345)

    low_latency = forwarder._build_low_latency_pipeline("rtsp://192.168.53.1/live")
    high_latency = forwarder._build_high_latency_pipeline("rtsp://192.168.53.1/live")

    for pipeline in (low_latency, high_latency):
        assert "rtph264depay request-keyframe=true wait-for-keyframe=true" in pipeline
        assert "h264parse config-interval=1" in pipeline
        assert "video/x-h264,stream-format=byte-stream,alignment=au" in pipeline
