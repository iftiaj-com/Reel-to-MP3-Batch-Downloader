import sys
import unittest
from unittest.mock import patch, MagicMock

# Create a mock streamlit module
import types
st_mock = types.ModuleType("streamlit")
st_mock.session_state = MagicMock()
st_mock.session_state.urls = ["http://example.com/reel/123"]
# Set step to something other than "input" or "processing" or "done" to bypass the huge if/elif block
st_mock.session_state.step = "mocking_test"

st_mock.progress = MagicMock()
st_mock.empty = MagicMock()
st_mock.info = MagicMock()
st_mock.success = MagicMock()
st_mock.error = MagicMock()
st_mock.rerun = MagicMock()
st_mock.set_page_config = MagicMock()
st_mock.markdown = MagicMock()
st_mock.title = MagicMock()
st_mock.text_area = MagicMock()
st_mock.button = MagicMock(return_value=False)
st_mock.warning = MagicMock()
st_mock.download_button = MagicMock()
st_mock.write = MagicMock()
st_mock.subheader = MagicMock()
st_mock.columns = MagicMock(return_value=(MagicMock(), MagicMock()))


def dummy_cache_data(*args, **kwargs):
    def decorator(func):
        return func
    return decorator
st_mock.cache_data = dummy_cache_data

# Mock Streamlit session state and functions
sys.modules["streamlit"] = st_mock

# Now we can import app safely
import app

class TestProxyLogic(unittest.TestCase):

    @patch('app.download_one')
    @patch('app.ProxyRotator')
    @patch('time.sleep', return_value=None) # Mock sleep so tests run fast
    def test_proxy_passed_to_download_one(self, mock_sleep, MockProxyRotator, mock_download_one):
        # Setup mocks
        mock_rotator_instance = MockProxyRotator.return_value
        mock_rotator_instance.current.return_value = "http://fake_proxy:8080"

        app.MAX_RETRIES = 2

        # Test Case 1: First attempt succeeds
        mock_download_one.return_value = "/tmp/fake/path.mp3"

        # We need to run the snippet from the processing block
        # Simulate the setup in app.py
        app.st.session_state.urls = ["http://example.com/reel/123"]
        app.st.session_state.step = "processing"

        # Run the loop logic manually
        temp_dir = "/tmp/fake_dir"
        log_area = MagicMock()
        url = "http://example.com/reel/123"

        rotator = MockProxyRotator()

        downloaded_path = None
        for attempt in range(1, app.MAX_RETRIES + 1):
            if attempt == 1:
                proxy = None
            else:
                backoff = app.RETRY_BASE * (2 ** (attempt - 2)) + app.random.uniform(0, 2)
                app.time.sleep(backoff)
                rotator.rotate()
                proxy = rotator.current()

            downloaded_path = app.download_one(url, temp_dir, proxy, log_area)
            if downloaded_path:
                break
            elif attempt > 1:
                rotator.rotate()

        # Assertions for Test Case 1
        mock_download_one.assert_called_once_with(url, temp_dir, None, log_area)
        self.assertEqual(downloaded_path, "/tmp/fake/path.mp3")

        # Test Case 2: First attempt fails, second attempt succeeds
        mock_download_one.reset_mock()
        mock_download_one.side_effect = [None, "/tmp/fake/path2.mp3"] # Fail first, succeed second

        downloaded_path = None
        for attempt in range(1, app.MAX_RETRIES + 1):
            if attempt == 1:
                proxy = None
            else:
                backoff = app.RETRY_BASE * (2 ** (attempt - 2)) + app.random.uniform(0, 2)
                app.time.sleep(backoff)
                rotator.rotate()
                proxy = rotator.current()

            downloaded_path = app.download_one(url, temp_dir, proxy, log_area)
            if downloaded_path:
                break
            elif attempt > 1:
                rotator.rotate()

        # Assertions for Test Case 2
        self.assertEqual(mock_download_one.call_count, 2)
        # First call should have proxy=None
        mock_download_one.assert_any_call(url, temp_dir, None, log_area)
        # Second call should have proxy="http://fake_proxy:8080"
        mock_download_one.assert_any_call(url, temp_dir, "http://fake_proxy:8080", log_area)
        self.assertEqual(downloaded_path, "/tmp/fake/path2.mp3")

if __name__ == '__main__':
    unittest.main()
