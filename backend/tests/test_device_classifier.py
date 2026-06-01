import unittest

from backend.services.device_classifier import classify_device


class DeviceClassifierTests(unittest.TestCase):
    def test_generic_ipp_port_does_not_force_printer_class(self):
        self.assertEqual(classify_device("", "alexs-macbook-pro", [631]), "Unknown")

    def test_jetdirect_port_still_identifies_printer(self):
        self.assertEqual(classify_device("", "office-printer", [9100]), "Printer")


if __name__ == "__main__":
    unittest.main()
