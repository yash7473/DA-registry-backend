"""The import enrichers read Master Data only through its API
(master_data_api.py): the request envelope and token, the geo index, and the
Kebele lookup by names or by id on top of it."""

import importlib
import sys
import unittest
from unittest import mock

sys.modules.setdefault("openg2p_registry_extensions", importlib.import_module("openg2p_registry_da_extension"))
from openg2p_registry_da_extension.ingestion_pipeline.enricher_services import master_data_api as api  # noqa: E402
from openg2p_registry_da_extension.ingestion_pipeline.enricher_services import g2p_da_enricher_services as enr  # noqa: E402

LEVELS = [{"level_id": "level-region", "level_mnemonic": "region"}, {"level_id": "level-zone", "level_mnemonic": "zone"},
          {"level_id": "level-woreda", "level_mnemonic": "woreda"}, {"level_id": "level-kebele", "level_mnemonic": "kebele"}]
VALUES = {
    "level-region": [{"level_value_id": "R1", "level_value_mnemonic": "Tigray", "parent_level_value_id": None}],
    "level-zone": [{"level_value_id": "Z1", "level_value_mnemonic": "North Western", "parent_level_value_id": "R1"}],
    "level-woreda": [{"level_value_id": "W1", "level_value_mnemonic": "Tahtay Adiyabo", "parent_level_value_id": "Z1"},
                     {"level_value_id": "W2", "level_value_mnemonic": "Laelay Adiyabo", "parent_level_value_id": "Z1"}],
    "level-kebele": [{"level_value_id": "K1", "level_value_mnemonic": "Adi Hageray", "parent_level_value_id": "W1"},
                     {"level_value_id": "K2", "level_value_mnemonic": "Adi Hageray", "parent_level_value_id": "W2"},
                     {"level_value_id": "K3", "level_value_mnemonic": "Badme", "parent_level_value_id": "W1"},
                     {"level_value_id": "K4", "level_value_mnemonic": "Badme", "parent_level_value_id": "W1"}],
}


def fake_post(path, payload=None, pagination=None):
    if path == "/geo/get_all_geo_levels":
        return LEVELS
    if path == "/geo/get_geo_level_values":
        return VALUES[payload["level_id"]]
    raise AssertionError(path)


class TestGeo(unittest.TestCase):
    def setUp(self):
        api.invalidate()
        enr._MasterDataGeo._name_index = None
        patcher = mock.patch.object(api, "post", side_effect=fake_post)
        self.post = patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(api.invalidate)

    def test_index_is_built_once_per_cache_period(self):
        api.geo_index()
        api.geo_index()
        self.assertEqual(self.post.call_count, 1 + len(LEVELS))

    def test_resolve_by_names_follows_the_chain(self):
        geo = enr._MasterDataGeo.resolve({"region": "tigray", "zone": "North Western", "woreda": "Tahtay Adiyabo", "kebele": "ADI HAGERAY"})
        self.assertEqual(geo["lowest_level_value_id"], "K1")  # not K2: same name under another woreda
        self.assertEqual([h["level_value_id"] for h in geo["hierarchy"]], ["R1", "Z1", "W1", "K1"])
        self.assertEqual(geo["hierarchy"][3], {"level": "kebele", "level_id": "level-kebele", "level_mnemonic": "kebele",
                                               "level_value_id": "K1", "level_value_mnemonic": "Adi Hageray"})

    def test_resolve_errors_name_the_place(self):
        base = {"region": "Tigray", "zone": "North Western", "woreda": "Tahtay Adiyabo"}
        with self.assertRaisesRegex(ValueError, "Kebele 'Nowhere' not found in Tigray / North Western / Tahtay Adiyabo"):
            enr._MasterDataGeo.resolve({**base, "kebele": "Nowhere"})
        with self.assertRaisesRegex(ValueError, "Kebele 'Badme' matches more than one place"):
            enr._MasterDataGeo.resolve({**base, "kebele": "Badme"})

    def test_resolve_by_id(self):
        geo = enr._MasterDataGeo.resolve_by_id("K2")
        self.assertEqual([h["level_value_id"] for h in geo["hierarchy"]], ["R1", "Z1", "W2", "K2"])
        with self.assertRaisesRegex(ValueError, "Location 'X' not found in Master Data"):
            enr._MasterDataGeo.resolve_by_id("X")
        with self.assertRaisesRegex(ValueError, "is a woreda, not a kebele"):
            enr._MasterDataGeo.resolve_by_id("W1")


class TestPost(unittest.TestCase):
    def setUp(self):
        api.invalidate()
        self.addCleanup(api.invalidate)

    def test_envelope_token_and_payload(self):
        env = {"REGISTRY_CELERY_WORKERS_MASTER_DATA_API_URL": "http://md", "REGISTRY_CELERY_WORKERS_MASTER_DATA_TOKEN_URL": "http://kc/token",
               "REGISTRY_CELERY_WORKERS_MASTER_DATA_CLIENT_ID": "c", "REGISTRY_CELERY_WORKERS_MASTER_DATA_CLIENT_SECRET": "s"}
        client = mock.MagicMock()
        client.__enter__.return_value = client
        token = mock.Mock(status_code=200); token.json.return_value = {"access_token": "T", "expires_in": 300}
        answer = mock.Mock(status_code=200); answer.json.return_value = {"response_header": {"response_status": "SUCCESS"}, "response_body": {"response_payload": [1]}}
        client.post.side_effect = [token, answer]
        with mock.patch.dict("os.environ", env), mock.patch.object(api.httpx, "Client", return_value=client):
            self.assertEqual(api.post("/geo/get_all_geo_levels"), [1])
        (url, ), kw = client.post.call_args_list[1]
        self.assertEqual(url, "http://md/geo/get_all_geo_levels")
        self.assertEqual(kw["headers"], {"Authorization": "Bearer T"})
        self.assertEqual(client.post.call_args_list[0].kwargs["data"]["grant_type"], "client_credentials")

    def test_error_answer_raises(self):
        client = mock.MagicMock(); client.__enter__.return_value = client
        answer = mock.Mock(status_code=200); answer.json.return_value = {"response_header": {"response_status": "ERROR", "response_error_message": "nope"}}
        client.post.return_value = answer
        no_token = {f"{p}MASTER_DATA_TOKEN_URL": "" for p in api.PREFIXES}
        with mock.patch.dict("os.environ", {**no_token, "REGISTRY_CELERY_WORKERS_MASTER_DATA_API_URL": "http://md"}), \
             mock.patch.object(api.httpx, "Client", return_value=client):
            with self.assertRaisesRegex(api.MasterDataUnavailable, "nope"):
                api.post("/geo/get_all_geo_levels")


if __name__ == "__main__":
    unittest.main()
