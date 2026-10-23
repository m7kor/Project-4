import unittest
from tools.diagnostics.pcsx2_probe_schema import connection_args


class Pcsx2SchemaTests(unittest.TestCase):
    def test_actual_enum_prefers_auto(self):
        schema = {'properties': {'mode': {'enum': ['auto', 'debug', 'pine']}}}
        self.assertEqual(connection_args(schema), {'mode': 'auto'})

    def test_debug_only_schema(self):
        self.assertEqual(connection_args({'properties': {'mode': {'enum': ['debug']}}}),
                         {'mode': 'debug'})

    def test_unknown_or_missing_schema_rejected(self):
        for schema in ({}, {'properties': {'mode': {'enum': ['debugserver']}}}):
            with self.assertRaises(ValueError):
                connection_args(schema)
