import pytest
import json
import io
from rate_limits_exporter import Checker, read_files_with_secrets


class MockTokenGetResponse:
    def __init__(self, text, status):
        self._text = text
        self.status = status

    async def __aexit__(self, exc_type, exc, tb):
        pass

    async def __aenter__(self):
        return self

    async def text(self):
        return self._text

    async def json(self):
        return json.loads(self._text)


class MockRateLimitsHeadResponse:
    def __init__(self, headers, status):
        self.status = status
        self.headers = headers

    async def __aexit__(self, exc_type, exc, tb):
        pass

    async def __aenter__(self):
        return self


# emulates incorrect directory path
class MockOSListDir:
    def __init__(self, path):
        self.path = path

    def __iter__(self):
        raise OSError

    def __next__(self):
        pass


@pytest.mark.asyncio
async def test_get_token(mocker):
    json_data = {'token': 'some_data'}
    client = Checker()

    resp = MockTokenGetResponse(json.dumps(json_data), 200)
    mocker.patch('aiohttp.ClientSession.get', return_value=resp)
    token = await client.get_token('', '')
    assert token == json_data['token']

    resp = MockTokenGetResponse(json.dumps(json_data), 401)
    mocker.patch('aiohttp.ClientSession.get', return_value=resp)
    token = await client.get_token('', '')
    assert token == ''

    resp = MockTokenGetResponse(json.dumps(json_data), 503)
    mocker.patch('aiohttp.ClientSession.get', return_value=resp)
    token = await client.get_token('', '')
    assert token == ''


@pytest.mark.asyncio
async def test_get_rate_limits(mocker):
    headers_dict = {
        'ratelimit-limit':      '100;w=21600',
        'ratelimit-remaining':  '100;w=21600'
    }
    client = Checker()

    resp = MockRateLimitsHeadResponse(headers_dict, 200)
    mocker.patch('aiohttp.ClientSession.head', return_value=resp)
    get_headers_dict = await client.get_rate_limit('token_str', '')
    assert headers_dict == get_headers_dict

    resp = MockRateLimitsHeadResponse(headers_dict, 503)
    mocker.patch('aiohttp.ClientSession.head', return_value=resp)
    get_headers_dict = await client.get_rate_limit('token_str', '')
    assert get_headers_dict == {}


def test_get_username():
    username = Checker().get_username('')
    assert username == 'Anonymous'

    username = Checker().get_username('User-1')
    assert username == 'User-1'


def test_get_dict_return_str_of_values():
    metrics_dict = {
        'key-1': 'key-1-value-1\nkey-1-value-2\n',
        'key-2': 'key-2-value-1\nkey-2-value-2\n'
    }
    metrics_str = Checker().get_dict_return_str_of_values(metrics_dict)
    assert metrics_str == 'key-1-value-1\nkey-1-value-2\nkey-2-value-1\nkey-2-value-2\n'

    metrics_dict = {'': ''}
    metrics_str = Checker().get_dict_return_str_of_values(metrics_dict)
    assert metrics_str == ''


def test_fill_metrics_help():
    headers_dict = {
        'ratelimit-limit':      '100;w=21600',
        'ratelimit-remaining':  '100;w=21600'
    }
    # we should create two separate objects (variable in Python is obj too)
    metrics_help_dict = Checker().fill_metrics_help({})
    metrics_values_dict = Checker().fill_metrics_help({})
    metrics_values_dict = Checker().fill_metrics(username='',
                                                 headers_dict=headers_dict,
                                                 metrics_dict=metrics_values_dict,
                                                 put_source_ip_in_label=False)

    # all items should not be equal
    equal_metrics_count_int = 0
    for k, v in metrics_help_dict.items():
        if v == metrics_values_dict[k]:
            print('The values before and after metrics assigment are equal. Possibly you have unused metric')
            equal_metrics_count_int += 1
    assert equal_metrics_count_int == 0


def test_configure_labels_set():
    headers_dict = {
        'docker-ratelimit-source':  '1.2.3.4'
    }
    labels_str = Checker().configure_labels_set(username='', headers_dict=headers_dict, put_source_ip_in_label=True)
    assert labels_str == 'dockerhub_user="Anonymous",source_ip="1.2.3.4"'

    labels_str = Checker().configure_labels_set(username='', headers_dict={}, put_source_ip_in_label=True)
    assert labels_str == 'dockerhub_user="Anonymous",source_ip=""'

    labels_str = Checker().configure_labels_set(username='User-1', headers_dict=headers_dict, put_source_ip_in_label=True)
    assert labels_str == 'dockerhub_user="User-1",source_ip="1.2.3.4"'

    labels_str = Checker().configure_labels_set(username='User-1', headers_dict={}, put_source_ip_in_label=True)
    assert labels_str == 'dockerhub_user="User-1",source_ip=""'


# we should be sure function always returns dict despite of any input headers combinations
def test_fill_metrics():
    headers_dict = {
        'ratelimit-limit': '100;w=21600',
        'ratelimit-remaining': '100;w=21600',
        'docker-ratelimit-source':  '1.2.3.4'
    }
    metrics_dict = Checker().fill_metrics_help({})
    metrics_dict = Checker().fill_metrics(username='',
                                          headers_dict=headers_dict,
                                          metrics_dict=metrics_dict,
                                          put_source_ip_in_label=True)
    assert isinstance(metrics_dict, dict)

    headers_dict = {
        'ratelimit-remaining': '100;w=21600',
        'docker-ratelimit-source':  '1.2.3.4'
    }
    metrics_dict = Checker().fill_metrics_help({})
    metrics_dict = Checker().fill_metrics(username='',
                                          headers_dict=headers_dict,
                                          metrics_dict=metrics_dict,
                                          put_source_ip_in_label=True)
    assert isinstance(metrics_dict, dict)

    headers_dict = {
        'ratelimit-limit': '100;w=21600',
        'docker-ratelimit-source':  '1.2.3.4'
    }
    metrics_dict = Checker().fill_metrics_help({})
    metrics_dict = Checker().fill_metrics(username='',
                                          headers_dict=headers_dict,
                                          metrics_dict=metrics_dict,
                                          put_source_ip_in_label=True)
    assert isinstance(metrics_dict, dict)

    headers_dict = {
        'ratelimit-limit': '100;w=21600',
        'ratelimit-remaining': '100;w=21600',
    }
    metrics_dict = Checker().fill_metrics_help({})
    metrics_dict = Checker().fill_metrics(username='',
                                          headers_dict=headers_dict,
                                          metrics_dict=metrics_dict,
                                          put_source_ip_in_label=True)
    assert isinstance(metrics_dict, dict)


@pytest.mark.asyncio
def test_read_files_with_secrets(mocker):
    # check empty dir
    path = '/fake/path'
    resp = []
    mocker.patch('os.listdir', return_value=resp)
    client = read_files_with_secrets(path)
    assert client == {'': ''}

    # check if directory path is exist
    path = '/fake/path'
    resp = MockOSListDir(path)
    mocker.patch('os.listdir', return_value=resp)
    client = read_files_with_secrets(path)
    assert client == {'': ''}

    file_name_str = 'file-1'
    file_data_str = 'file-data'
    resp = [file_name_str]
    mocker.patch('os.listdir', return_value=resp)
    # creates file-like obj in memory with appropriate methods like read() and write()
    file = io.StringIO(file_data_str)
    mocker.patch("builtins.open", return_value=file)
    client = read_files_with_secrets(path)
    assert client == {file_name_str: file_data_str}
