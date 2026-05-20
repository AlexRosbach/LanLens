import csv
import io
import unittest

from backend.services.idoit import rows_to_export_csv


class IdoitExportCsvTest(unittest.TestCase):
    def test_rows_to_export_csv_skips_unchecked_rows(self):
        csv_body = rows_to_export_csv([
            {
                "include": True,
                "object_type": "C__OBJTYPE__CLIENT",
                "title": "included",
                "ip_address": "192.0.2.10",
                "mac_address": "00:11:22:33:44:55",
            },
            {
                "include": False,
                "object_type": "C__OBJTYPE__CLIENT",
                "title": "excluded",
                "ip_address": "192.0.2.20",
            },
        ])

        rows = list(csv.DictReader(io.StringIO(csv_body.lstrip("\ufeff")), delimiter=";"))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Bezeichnung"], "included")
        self.assertEqual(rows[0]["IP-Adresse"], "192.0.2.10")
        self.assertIn("SNMP-Switch", rows[0])
        self.assertIn("Identity Confidence", rows[0])


if __name__ == "__main__":
    unittest.main()
