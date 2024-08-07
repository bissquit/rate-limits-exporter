import pytest
import json
from rate_limits_exporter import Metrics, get_username, handle_credentials, DockerHubClient


class MockTokenResponse:
    def __init__(self, text, status, headers=None):
        self._text = text
        self.status = status
        self.headers = headers

    async def __aexit__(self, exc_type, exc, tb):
        pass

    async def __aenter__(self):
        return self

    async def text(self):
        return self._text

    async def json(self):
        return json.loads(self._text)


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
    client = DockerHubClient()

    resp = MockTokenResponse(json.dumps(json_data), 200)
    mocker.patch('aiohttp.ClientSession.get', return_value=resp)
    token = await client.get_token('', '')
    assert token == json_data['token']

    resp = MockTokenResponse(json.dumps(json_data), 401)
    mocker.patch('aiohttp.ClientSession.get', return_value=resp)
    token = await client.get_token('', '')
    assert token == ''

    resp = MockTokenResponse(json.dumps(json_data), 503)
    mocker.patch('aiohttp.ClientSession.get', return_value=resp)
    token = await client.get_token('', '')
    assert token == ''


@pytest.mark.asyncio
async def test_get_rate_limits(mocker):
    headers_dict = {
        'ratelimit-limit':      '100;w=21600',
        'ratelimit-remaining':  '100;w=21600'
    }
    client = DockerHubClient()

    resp = MockTokenResponse(headers_dict, 200, headers_dict)
    mocker.patch('aiohttp.ClientSession.head', return_value=resp)
    get_headers_dict = await client.get_rate_limit('token_str', '')
    assert headers_dict == get_headers_dict

    resp = MockTokenResponse(headers_dict, 503, headers_dict)
    mocker.patch('aiohttp.ClientSession.head', return_value=resp)
    get_headers_dict = await client.get_rate_limit('token_str', '')
    assert get_headers_dict == {}


async def mock_awaitable_obj(mocked_dict):
    return mocked_dict


@pytest.mark.asyncio
async def test_client_handler(mocker):
    client = DockerHubClient()

    get_token_resp = await mock_awaitable_obj('')
    mocker.patch('rate_limits_exporter.DockerHubClient.get_token', return_value=get_token_resp)
    get_rate_limit_resp = await mock_awaitable_obj({})
    mocker.patch('rate_limits_exporter.DockerHubClient.get_rate_limit', return_value=get_rate_limit_resp)
    result = await client.client_handler('', '')
    assert result == {}

    not_empty_str = 'not_empty_str'
    get_token_resp = await mock_awaitable_obj(not_empty_str)
    mocker.patch('rate_limits_exporter.DockerHubClient.get_token', return_value=get_token_resp)
    get_rate_limit_resp = await mock_awaitable_obj({})
    mocker.patch('rate_limits_exporter.DockerHubClient.get_rate_limit', return_value=get_rate_limit_resp)
    result = await client.client_handler('', '')
    assert result == {}


def test_get_username():
    username = get_username('')
    assert username == 'Anonymous'

    username = get_username('User-1')
    assert username == 'User-1'


def test_get_dict_return_str_of_values():
    metrics_dict = {
        'key-1': 'key-1-value-1\nkey-1-value-2\n',
        'key-2': 'key-2-value-1\nkey-2-value-2\n'
    }
    metrics_str = Metrics().get_dict_return_str_of_values(metrics_dict)
    assert metrics_str == 'key-1-value-1\nkey-1-value-2\nkey-2-value-1\nkey-2-value-2\n'

    metrics_dict = {'': ''}
    metrics_str = Metrics().get_dict_return_str_of_values(metrics_dict)
    assert metrics_str == ''


def test_fill_metrics_help():
    headers_dict = {
        'ratelimit-limit':      '100;w=21600',
        'ratelimit-remaining':  '100;w=21600'
    }
    # we should create two separate objects (variable in Python is obj too)
    metrics_help_dict = Metrics().fill_metrics_help({})
    metrics_values_dict = Metrics().fill_metrics_help({})
    metrics_values_dict = Metrics().fill_metrics(username='',
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
    labels_str = Metrics().configure_labels_set(username='', headers_dict=headers_dict, put_source_ip_in_label=True)
    assert labels_str == 'dockerhub_user="Anonymous",source_ip="1.2.3.4"'

    labels_str = Metrics().configure_labels_set(username='', headers_dict={}, put_source_ip_in_label=True)
    assert labels_str == 'dockerhub_user="Anonymous",source_ip=""'

    labels_str = Metrics().configure_labels_set(username='User-1', headers_dict=headers_dict, put_source_ip_in_label=True)
    assert labels_str == 'dockerhub_user="User-1",source_ip="1.2.3.4"'

    labels_str = Metrics().configure_labels_set(username='User-1', headers_dict={}, put_source_ip_in_label=True)
    assert labels_str == 'dockerhub_user="User-1",source_ip=""'


# we should be sure the function always returns dict despite any input headers combinations
def test_fill_metrics():
    headers_dict = {
        'ratelimit-limit': '100;w=21600',
        'ratelimit-remaining': '100;w=21600',
        'docker-ratelimit-source':  '1.2.3.4'
    }
    metrics_dict = Metrics().fill_metrics_help({})
    metrics_dict = Metrics().fill_metrics(username='',
                                          headers_dict=headers_dict,
                                          metrics_dict=metrics_dict,
                                          put_source_ip_in_label=True)
    assert isinstance(metrics_dict, dict)

    headers_dict = {
        'ratelimit-remaining': '100;w=21600',
        'docker-ratelimit-source':  '1.2.3.4'
    }
    metrics_dict = Metrics().fill_metrics_help({})
    metrics_dict = Metrics().fill_metrics(username='',
                                          headers_dict=headers_dict,
                                          metrics_dict=metrics_dict,
                                          put_source_ip_in_label=True)
    assert isinstance(metrics_dict, dict)

    headers_dict = {
        'ratelimit-limit': '100;w=21600',
        'docker-ratelimit-source':  '1.2.3.4'
    }
    metrics_dict = Metrics().fill_metrics_help({})
    metrics_dict = Metrics().fill_metrics(username='',
                                          headers_dict=headers_dict,
                                          metrics_dict=metrics_dict,
                                          put_source_ip_in_label=True)
    assert isinstance(metrics_dict, dict)

    headers_dict = {
        'ratelimit-limit': '100;w=21600',
        'ratelimit-remaining': '100;w=21600',
    }
    metrics_dict = Metrics().fill_metrics_help({})
    metrics_dict = Metrics().fill_metrics(username='',
                                          headers_dict=headers_dict,
                                          metrics_dict=metrics_dict,
                                          put_source_ip_in_label=True)
    assert isinstance(metrics_dict, dict)


def test_handle_credentials():
    account_dict = handle_credentials('', '')
    assert account_dict == {'': ''}

    account_dict = handle_credentials('name', 'pass_of_some_account')
    assert account_dict == {'name': 'pass_of_some_account'}

    try:
        account_dict = handle_credentials('name', '')
    except BaseException:
        print(Exception)
        assert True

    try:
        account_dict = handle_credentials('', 'pass_of_some_account')
    except BaseException:
        assert True
