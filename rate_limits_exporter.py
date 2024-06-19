import os
import re
import aiohttp
from aiohttp import web
import asyncio
import logging
import argparse

logging.basicConfig(level=os.getenv("LOG_LEVEL", logging.DEBUG), format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def parse_args():
    # You may either use command line argument or env variables
    parser = argparse.ArgumentParser(prog='rate_limits_exporter',
                                     description='Docker Hub rate limits exporter for Prometheus')
    parser.add_argument('-d', '--directory',
                        default=os.getenv('APP_SECRETS_DIR', '/opt/secrets/'),
                        type=str,
                        help='Directory with files. The name of file - username of DockerHub, file content - password. (default: /opt)')
    parser.add_argument('-p', '--port',
                        default=os.getenv("APP_PORT", 8080),
                        type=int,
                        help='Port to be listened (default: 8080)')
    parser.add_argument('-t', '--time',
                        default=os.getenv("APP_CHECK_INTERVAL", 60),
                        type=int,
                        help='Default time range in seconds to perform rate limits check (default: 60)')
    parser.add_argument('-s', '--source',
                        default=os.getenv("APP_PUT_SOURCE_IP", False),
                        type=bool,
                        help='Put source ip address into labels set (default: False)')
    return parser.parse_args()


class DockerHubClient:
    def __init__(self, token_url="https://auth.docker.io/token?service=registry.docker.io&scope=repository:ratelimitpreview/test:pull",
                 limits_url="https://registry-1.docker.io/v2/ratelimitpreview/test/manifests/latest"):
        self.token_url = token_url
        self.limits_url = limits_url

    async def client_handler(self, username, password):
        # we have to renew token before each request because for some reasons Docker Hub
        # doesn't return required headers several minutes before token expiration
        # while status code is 200 (not 401)
        token_str = await self.get_token(username=username, password=password)
        headers_dict = await self.get_rate_limit(username=username, token=token_str)
        return headers_dict

    async def get_token(self, username, password):
        token_str = ''
        # Unauthenticated (anonymous) users will have the limits enforced via IP
        if username:
            auth = aiohttp.BasicAuth(login=username, password=password)
        else:
            auth = None

        async with aiohttp.ClientSession(auth=auth) as client:
            try:
                async with client.get(self.token_url) as r:
                    status = r.status
                    logger.info(f'Getting token for {get_username(username)} user')
                    logger.debug(f'Full response: {r}')
                    if status == 200:
                        json_body = await r.json()
                        token_str = json_body['token']
                    else:
                        logger.error(f'Cannot renew token for {get_username(username)} user! Response status: {status}')
            except aiohttp.ClientConnectionError as error:
                logger.error(f'Connection error during updating token: {error}')
        return token_str

    async def get_rate_limit(self, username, token):
        headers_dict = {}
        headers = {'Authorization': f'Bearer {token}'}
        async with aiohttp.ClientSession(headers=headers) as client:
            try:
                # Headers will be returned on both GET and HEAD requests. Note that using GET
                # emulates a real pull and will count towards the limit; using HEAD will not
                async with client.head(self.limits_url) as r:
                    status = r.status
                    logger.info(f'Checking ratelimits. Response status: {status}')
                    logger.debug(f'Full response: {r}')
                    if status == 200:
                        headers_dict = r.headers
                    else:
                        logger.error(f'Cannot get rate limits for {get_username(username)} user! Response status: {status}')
            except aiohttp.ClientConnectionError as error:
                logger.error(f'Connection error during getting rate limits: {error}')
        return headers_dict


class Metrics:
    def __init__(self):
        pass

    async def handler(self, accounts_dict, put_source_ip_in_label=False):
        metrics_dict = self.fill_metrics_help({})
        # getting headers for each account and produce metrics
        for username, password in accounts_dict.items():
            headers_dict = await DockerHubClient().client_handler(username=username, password=password)
            metrics_dict = self.fill_metrics(username=username,
                                             headers_dict=headers_dict,
                                             metrics_dict=metrics_dict,
                                             put_source_ip_in_label=put_source_ip_in_label)
        metrics_str = self.get_dict_return_str_of_values(metrics_dict=metrics_dict)
        return metrics_str

    @staticmethod
    def get_dict_return_str_of_values(metrics_dict):
        metrics_str = ''
        # paste all item's values into one str
        for metric_name, metric_value in metrics_dict.items():
            metrics_str += metric_value
        return metrics_str

    @staticmethod
    def configure_labels_set(username, headers_dict, put_source_ip_in_label):
        username_str = get_username(username)
        if 'docker-ratelimit-source' in headers_dict and put_source_ip_in_label:
            source_ip_str = headers_dict['docker-ratelimit-source']
        else:
            # label with empty value will be treated as no label
            source_ip_str = ''
        labels_str = f'dockerhub_user="{username_str}",source_ip="{source_ip_str}"'
        return labels_str

    @staticmethod
    def fill_metrics_help(metrics_dict):
        metrics_dict['dockerhub_ratelimit_current'] = '# HELP dockerhub_ratelimit_current Current max limit for DockerHub account (or for ip address if anonymous access)\n'
        metrics_dict['dockerhub_ratelimit_current'] += '# TYPE dockerhub_ratelimit_current gauge\n'
        metrics_dict['dockerhub_ratelimit_remaining'] = '# HELP dockerhub_ratelimit_remaining Remaining limit for DockerHub account (or for ip address if anonymous access)\n'
        metrics_dict['dockerhub_ratelimit_remaining'] += '# TYPE dockerhub_ratelimit_remaining gauge\n'
        metrics_dict['dockerhub_ratelimit_scrape_error'] = '# HELP dockerhub_ratelimit_scrape_error Scrape errors (wrong status code or something else)\n'
        metrics_dict['dockerhub_ratelimit_scrape_error'] += '# TYPE dockerhub_ratelimit_scrape_error gauge\n'
        return metrics_dict

    def fill_metrics(self, username, headers_dict, metrics_dict, put_source_ip_in_label):
        labels_str = self.configure_labels_set(username, headers_dict, put_source_ip_in_label)

        if 'ratelimit-limit' in headers_dict and 'ratelimit-remaining' in headers_dict:
            logger.debug('Headers returned successfully. Configuring metrics...')
            # headers strings look like 100;w=21600. We need the first number
            ratelimit_limit = re.search(r'^\d*', headers_dict['ratelimit-limit']).group()
            ratelimit_remaining = re.search(r'^\d*', headers_dict['ratelimit-remaining']).group()
            metrics_dict['dockerhub_ratelimit_current'] += f'dockerhub_ratelimit_current{{{labels_str}}} {ratelimit_limit}\n'
            metrics_dict['dockerhub_ratelimit_remaining'] += f'dockerhub_ratelimit_remaining{{{labels_str}}} {ratelimit_remaining}\n'
            metrics_dict['dockerhub_ratelimit_scrape_error'] += f'dockerhub_ratelimit_scrape_error{{{labels_str}}} 0\n'
        # not empty but without expected headers
        elif headers_dict:
            # request may not contain rate limits headers for some reasons
            # even with 200 status code so we have to check it
            logger.info('There aren\'t expected headers. Maybe current Docker Hub account doesn\'t have any limits. Metrics won\'t be returned')
        else:
            logger.error('Empty headers returned')
            metrics_dict['dockerhub_ratelimit_scrape_error'] += f'dockerhub_ratelimit_scrape_error{{{labels_str}}} 1\n'
        return metrics_dict


def get_username(username):
    return username if username else "Anonymous"


# https://docs.aiohttp.org/en/stable/web_quickstart.html#handler
# A request handler must be a coroutine that accepts
# a Request instance as its only parameter...
async def metrics_handler(request):
    # ... and returns a Response instance
    return web.Response(text=request.app['metrics_str'])


async def start_background_tasks(app):
    app['rate_limits_checker'] = asyncio.create_task(background_task(app))


async def cleanup_background_tasks(app):
    app['rate_limits_checker'].cancel()
    await app['rate_limits_checker']


async def background_task(app):
    accounts_dict = app['accounts_dict']
    while True:
        metrics_str = await Metrics().handler(accounts_dict=accounts_dict,
                                              put_source_ip_in_label=app['args'].source)
        app['metrics_str'] = metrics_str
        await asyncio.sleep(app['args'].time)


def read_files_with_secrets(path):
    """
    :param path: each filename in the directory have to be a DockerHub account name. File data is a password
    :return: dict with username : password pairs or empty dict if directory is empty
    """
    accounts_dict = {}
    try:
        files_list = os.listdir(path=path)
        if not files_list:
            logger.info(f'Directory {path} is empty. Skipping reading files. DockerHub limits will be checked for external ip')
        else:
            for file_name in files_list:
                full_file_path = f'{path}/{file_name}'
                logger.info(f'Reading file {full_file_path}')
                # read file data with trailing characters removed
                file_data = open(full_file_path).read().rstrip()
                accounts_dict[file_name] = file_data
    except OSError as error:
        logger.warning(f'Could not list files in directory {path}: {error}')

    if not accounts_dict:
        # we have not to return empty dict if dir is empty. The dict {'': ''} is not empty
        accounts_dict = {'': ''}
    return accounts_dict


def main():
    args = parse_args()
    app = web.Application()
    # For storing global-like variables, feel free to save them in an Application instance
    app['accounts_dict'] = read_files_with_secrets(args.directory)  # {'username1': 'password1', {username2}: ...}
    app['metrics_str'] = 'Initialization'
    app['args'] = args
    app.add_routes([web.get('/metrics', metrics_handler)])
    # https://docs.aiohttp.org/en/stable/web_advanced.html#background-tasks
    app.on_startup.append(start_background_tasks)
    app.on_cleanup.append(cleanup_background_tasks)
    web.run_app(app, port=args.port)


if __name__ == "__main__":
    main()
