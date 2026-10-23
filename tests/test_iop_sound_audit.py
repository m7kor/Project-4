import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("iop_sound_audit", Path(__file__).resolve().parents[1] / "tools/diagnostics/iop_sound_audit.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def row(ordinal, cycle, a0=0, a1=0, a2=0, valid=1):
    return (f"[ps2xIOP] [IOP sound import] ordinal={ordinal} cycles={cycle} pc=0x1000 "
            f"ra=0x2008 target=0x3000 gp=0x4000 a0=0x{a0:x} a1=0x{a1:x} "
            f"a2=0x{a2:x} a3=0x5020 a4=0x400 a4_valid={valid} control=0x1\n")


class SoundAuditTests(unittest.TestCase):
    def test_init_and_quit_invalidate_both_cores_without_claiming_zero_handlers(self):
        for ordinal in (2, 4):
            result = module.summarize([row(26, 1, 0, 0xAAAA), row(26, 2, 1, 0xBBBB),
                                       row(ordinal, 3), row(17, 4), row(17, 5, a0=1)])
            for event in result["events"][-2:]:
                self.assertIsNone(event["last_observed_transfer_handler"])
            self.assertTrue(result["usable"])

    def test_replacement_is_per_core_and_reset_does_not_inherit_handler(self):
        result = module.summarize([row(26, 10, 0, 0xAAAA, 0x1111),
                                   row(26, 11, 1, 0xBBBB, 0x2222), row(17, 12),
                                   row(26, 13, 0, 0xCCCC, 0x3333), row(17, 14),
                                   row(17, 1)])
        transfers = [e for e in result["events"] if e["kind"] == "voice-transfer"]
        self.assertEqual(transfers[0]["last_observed_transfer_handler"]["function"], 0xAAAA)
        self.assertEqual(transfers[1]["last_observed_transfer_handler"]["function"], 0xCCCC)
        self.assertIsNone(transfers[2]["last_observed_transfer_handler"])
        self.assertEqual(transfers[2]["segment"], 1)
        self.assertTrue(result["usable"])

    def test_missing_size_and_malformed_observations_cannot_be_usable(self):
        for trace in ([row(17, 10, valid=0)], [row(26, 10, a0=2)],
                      ["[IOP sound import] ordinal=17 cycles=1\n"], []):
            self.assertFalse(module.summarize(trace)["usable"])

    def test_cap_is_reported_and_irq_registration_does_not_replace_transfer_handler(self):
        trace = [row(26, 1, 0, 0xAAAA), row(27, 2, 0xBBBB)]
        trace += [row(17, cycle) for cycle in range(3, 131)]
        result = module.summarize(trace)
        self.assertTrue(result["potentially_capped"])
        self.assertEqual(result["events"][-1]["last_observed_transfer_handler"]["function"], 0xAAAA)
