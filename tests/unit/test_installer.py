import unittest
from lucid_agent_core import installer


class TestInstaller(unittest.TestCase):
    def test_wheel_filename(self):
        self.assertEqual(
            installer._wheel_filename("0.1.1"),
            "lucid_agent_core-0.1.1-py3-none-any.whl",
        )

    def test_release_wheel_url(self):
        url = installer._release_wheel_url("0.1.1")
        self.assertIn("/releases/download/v0.1.1/", url)
        self.assertTrue(url.endswith("lucid_agent_core-0.1.1-py3-none-any.whl"))


if __name__ == "__main__":
    unittest.main()
