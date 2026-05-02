from hostile_mesh_runtime.context.loop_detector import LoopDetector


def test_detects_exact_repeats():
    d = LoopDetector(max_exact_repeats=3, max_cycle_length=3)
    for _ in range(3):
        d.record("tool_call", tool_name="probe", args={"path": "/users/1"})
    assert d.check() is not None


def test_does_not_flag_below_threshold():
    d = LoopDetector(max_exact_repeats=3, max_cycle_length=3)
    for _ in range(2):
        d.record("tool_call", tool_name="probe", args={"path": "/users/1"})
    assert d.check() is None


def test_detects_two_step_cycle():
    d = LoopDetector(max_exact_repeats=4, max_cycle_length=3)
    for _ in range(3):
        d.record("tool_call", tool_name="probe", args={"path": "/a"})
        d.record("tool_call", tool_name="probe", args={"path": "/b"})
    assert "cycle" in (d.check() or "")


def test_arg_order_doesnt_matter():
    d1 = LoopDetector(max_exact_repeats=2, max_cycle_length=3)
    d2 = LoopDetector(max_exact_repeats=2, max_cycle_length=3)
    d1.record("tool_call", tool_name="probe", args={"path": "/x", "qs": "a"})
    d1.record("tool_call", tool_name="probe", args={"path": "/x", "qs": "a"})
    d2.record("tool_call", tool_name="probe", args={"qs": "a", "path": "/x"})
    d2.record("tool_call", tool_name="probe", args={"qs": "a", "path": "/x"})
    assert d1.check() is not None and d2.check() is not None
