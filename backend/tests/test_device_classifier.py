import unittest

from backend.services.device_classifier import classify_device


class DeviceClassifierTests(unittest.TestCase):
    def test_generic_ipp_port_does_not_force_printer_class(self):
        self.assertEqual(classify_device("", "alexs-macbook-pro", [631]), "Unknown")

    def test_jetdirect_port_still_identifies_printer(self):
        self.assertEqual(classify_device("", "office-printer", [9100]), "Printer")

    def test_generic_rtsp_port_does_not_force_camera_class(self):
        self.assertEqual(classify_device("", "alexs-macbook-pro", [554]), "Unknown")

    def test_hostname_tokens_do_not_match_inside_personal_names(self):
        self.assertEqual(classify_device("", "switcher-macbook", []), "Unknown")
        self.assertEqual(classify_device("", "printerfriendly-laptop", []), "Unknown")

    def test_specific_switch_vendor_beats_generic_network_vendor(self):
        self.assertEqual(classify_device("Netgear Switch", "", []), "Switch")

    def test_explicit_device_hostnames_still_classify(self):
        self.assertEqual(classify_device("", "office-printer-01", []), "Printer")
        self.assertEqual(classify_device("", "core-switch-01", []), "Switch")
        self.assertEqual(classify_device("", "garage-camera-01", []), "Camera")


if __name__ == "__main__":
    unittest.main()
