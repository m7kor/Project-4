import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("gif_dma_source_audit", Path(__file__).resolve().parents[1] /
                                            "tools/diagnostics/gif_dma_source_audit.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class DmaSourceAuditTests(unittest.TestCase):
    def line(self, count=16):
        return (f"[GIF DMA source] index=0 stage=chain tag=4096 id=3 source=8192 scratch=0 "
                f"bytes={count} chain_offset=96 prefix=" + "ab" * min(count, 64))

    def test_full_span_and_prefix_have_distinct_scope(self):
        self.assertTrue(module.audit(self.line())["events"][0]["captured_whole_span"])
        result = module.audit(self.line(1024))
        self.assertTrue(result["usable"])
        self.assertFalse(result["events"][0]["captured_whole_span"])
        self.assertTrue(module.audit(self.line() + "\n[GIF DMA source trace capped] limit=1024")["potentially_capped"])

    def test_bad_or_missing_evidence_is_rejected(self):
        line = self.line()
        for trace in ("", line[:-2], line+"\n"+line, line.replace("source=8192", "source=33554430"),
                      line.replace("scratch=0", "scratch=2"), line.replace("id=3", "id=8"),
                      line.replace("stage=chain", "stage=linear")):
            with self.subTest(trace=trace):
                self.assertFalse(module.audit(trace)["usable"])
