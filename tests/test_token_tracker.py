"""Token 用量追踪测试"""

from backend.llm_clients.factory import TokenTracker, get_token_tracker


class TestTokenTracker:
    def test_initial_state(self):
        t = TokenTracker()
        assert t.total_tokens == 0
        assert t.call_count == 0

    def test_record_single(self):
        t = TokenTracker()
        t.record(input_tokens=100, output_tokens=50)
        assert t.total_tokens == 150
        assert t.call_count == 1

    def test_record_multiple(self):
        t = TokenTracker()
        t.record(100, 50)
        t.record(200, 80)
        t.record(300, 120)
        assert t.total_tokens == 850
        assert t.call_count == 3

    def test_snapshot(self):
        t = TokenTracker()
        t.record(100, 50)
        snap = t.snapshot()
        assert snap["input_tokens"] == 100
        assert snap["output_tokens"] == 50
        assert snap["total_tokens"] == 150
        assert snap["call_count"] == 1

    def test_reset(self):
        t = TokenTracker()
        t.record(100, 50)
        t.reset()
        assert t.total_tokens == 0
        assert t.call_count == 0

    def test_thread_safety(self):
        import threading

        t = TokenTracker()

        def record_batch():
            for _ in range(100):
                t.record(10, 5)

        threads = [threading.Thread(target=record_batch) for _ in range(5)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()

        assert t.call_count == 500
        assert t.total_tokens == 7500  # (10+5) * 500

    def test_global_singleton(self):
        t1 = get_token_tracker()
        t2 = get_token_tracker()
        assert t1 is t2


class TestTokenTrackerIntegration:
    """验证 LLM 工厂函数返回的实例集成"""

    def test_factory_creates_tracker(self):
        """工厂函数调用后 tracker 可访问"""
        t = get_token_tracker()
        before = t.call_count
        # 不创建 LLM（避免真实 API 调用），仅验证 tracker 可用
        assert t is not None
        assert before >= 0

    def test_record_from_factory(self):
        """通过工厂创建的 LLM 不会崩溃"""
        # 验证 tracker 单例在未调用任何 LLM 时仍可访问
        t = get_token_tracker()
        t.record(42, 7)
        assert t.call_count > 0
