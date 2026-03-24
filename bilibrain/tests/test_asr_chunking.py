from bilibrain.ai.clients import plan_silence_aligned_ranges, trim_repeated_prefix


def test_plan_silence_aligned_ranges_prefers_nearby_silence():
    result = plan_silence_aligned_ranges(
        duration_seconds=260.0,
        silence_points=[88.0, 179.5, 246.0],
        target_seconds=90.0,
        max_seconds=120.0,
    )
    assert result == [(0.0, 88.0), (88.0, 179.5), (179.5, 260.0)]


def test_trim_repeated_prefix_removes_overlap_echo():
    previous = "今天我们先讲 FastAPI 的依赖注入和请求生命周期"
    current = "依赖注入和请求生命周期，然后再看中间件怎么接进去"
    result = trim_repeated_prefix(previous, current)
    assert result == "然后再看中间件怎么接进去"
