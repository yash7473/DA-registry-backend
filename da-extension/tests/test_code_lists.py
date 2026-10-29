"""The import enrichers resolve coded values against Master Data lists
(code_lists.py): code, display or translation, case-insensitive; anything else
names the allowed displays. Imports openg2p_registry_core (container)."""

import importlib
import sys
import unittest
from unittest import mock

sys.modules.setdefault("openg2p_registry_extensions", importlib.import_module("openg2p_registry_da_extension"))
from openg2p_registry_da_extension.ingestion_pipeline.enricher_services import code_lists as cl  # noqa: E402

REG = "6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90"
SCHEMA = {"widgets": [
    {"widget": "select", "widget-id": "position", "widget-label": "Position", "widget-data-path": f"{REG}.position",
     "widget-data-source": {"type": "api", "service": "attributes", "endpoint": "values", "params": {"attribute_id": "DA_POSITION"}}},
    {"widget": "input", "widget-id": "first_name", "widget-label": "Name", "widget-data-path": f"{REG}.first_name"},
]}
VALUES = {"DEVELOPMENT_AGENT": "Development Agent", "SENIOR_DA": "Senior DA", "SUPERVISOR": "Supervisor",
          "__i18n__SUPERVISOR": '{"am": "ተቆጣጣሪ"}', "__code__SUP": "SUPERVISOR"}


class TestResolve(unittest.TestCase):
    def setUp(self):
        cl.invalidate()
        session = mock.Mock()
        session.execute.return_value.scalars.return_value.all.return_value = [SCHEMA]
        self.session = session
        self.values = mock.patch.object(cl, "attribute_values", return_value=VALUES); self.values.start(); self.addCleanup(self.values.stop)
        self.addCleanup(cl.invalidate)

    def test_field_attributes_come_from_the_form_metadata(self):
        self.assertEqual(cl.field_attributes(self.session), ({"position": "DA_POSITION"}, {"position": "Position", "first_name": "Name"}))

    def test_code_display_translation_and_alternate_code_resolve(self):
        for given in ("SENIOR_DA", "senior da", "Senior DA", "senior-da"):
            self.assertEqual(cl.resolve_code("position", given, self.session), "SENIOR_DA", given)
        self.assertEqual(cl.resolve_code("position", "ተቆጣጣሪ", self.session), "SUPERVISOR")
        self.assertEqual(cl.resolve_code("position", "sup", self.session), "SUPERVISOR")
        self.assertIsNone(cl.resolve_code("position", "  ", self.session))

    def test_a_value_added_in_master_data_is_accepted_without_a_code_change(self):
        self.assertEqual(cl.resolve_code("position", "Supervisor", self.session), "SUPERVISOR")

    def test_unknown_value_lists_the_displays(self):
        with self.assertRaises(ValueError) as ctx:
            cl.resolve_code("position", "Manager", self.session)
        self.assertEqual(str(ctx.exception), "Position 'Manager' is not one of: Development Agent, Senior DA, Supervisor")

    def test_uncoded_field_passes_through(self):
        self.assertEqual(cl.resolve_code("first_name", " Abebe ", self.session), "Abebe")

class TestApiRead(unittest.TestCase):
    """A list is read from the Master Data API, never from its database."""

    def setUp(self):
        cl.invalidate()
        self.addCleanup(cl.invalidate)

    def test_values_codes_and_translations_from_the_api(self):
        payload = {"attribute_values": [
            {"value_id": "SENIOR_DA", "value_code": "SENIOR_DA", "value_display": "Senior DA", "display_i18n": {"am": "x"}},
            {"value_id": "DA", "value_code": "DEV_AGENT", "value_display": "Development Agent"},
        ]}
        with mock.patch.object(cl.master_data_api, "post", return_value=payload) as post:
            values = cl.attribute_values("DA_POSITION")
            cl.attribute_values("DA_POSITION")  # cached
        post.assert_called_once_with("/attributes/get_attribute_values", {"attribute_id": "DA_POSITION"},
                                     {"current_page": 1, "page_size": 1000})
        self.assertEqual(values["SENIOR_DA"], "Senior DA")
        self.assertEqual(values["__i18n__SENIOR_DA"], '{"am": "x"}')
        self.assertEqual(values["__code__DEV_AGENT"], "DA")


if __name__ == "__main__":
    unittest.main()
