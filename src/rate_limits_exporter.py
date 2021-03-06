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
    return parser.parse_args()


class Checker:
    def __init__(self):
        self.token_url = "https://auth.docker.io/token?service=registry.docker.io&scope=repository:ratelimitpreview/test:pull"
        self.limits_url = "https://registry-1.docker.io/v2/ratelimitpreview/test/manifests/latest"

    async def entrypoint(self, app):
        tokens_dict = {}
        # fill accounts with empty tokens (they will be renewed in further)
        for account in app['accounts_dict']:
            tokens_dict = {account: ''}
        while True:
            metrics_dict = self.fill_metrics_help({})
            for username, password in app['accounts_dict'].items():
                # we have to renew token before each request because for some reasons Docker Hub
                # doesn't return required headers several minutes before token expiration
                # while status code is 200 (not 401)
                tokens_dict[username] = await self.get_token(username, password)
                headers_dict = await self.get_rate_limit(token=tokens_dict[username], username=username)
                metrics_dict = self.fill_metrics(username, headers_dict, metrics_dict)
            # I don't know workaround yet but:
            # DeprecationWarning: Changing state of started or joined application is deprecated
            app['metrics_str'] = self.get_dict_return_str_of_values(metrics_dict)
            await asyncio.sleep(app['args'].time)

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
                    logger.info(f'Getting token for {self.set_username(username)} user')
                    logger.debug(f'Full response: {r}')
                    if status == 200:
                        json_body = await r.json()
                        token_str = json_body['token']
                    else:
                        logger.error(f'Cannot renew token for {self.set_username(username)} user! Response status: {status}')
            except aiohttp.ClientConnectionError as error:
                logger.error(f'Connection error during updating token: {error}')
        return token_str

    async def get_rate_limit(self, token, username):
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
                        logger.error(f'Cannot get rate limits for {self.set_username(username)} user! Response status: {status}')
            except aiohttp.ClientConnectionError as error:
                logger.error(f'Connection error during getting rate limits: {error}')
        return headers_dict

    @staticmethod
    def set_username(username):
        return username if username else "Anonymous"

    @staticmethod
    def get_dict_return_str_of_values(metrics_dict):
        metrics_str = ''
        # paste all item's values into one str
        for metric_name, metric_value in metrics_dict.items():
            metrics_str += metric_value
        return metrics_str

    @staticmethod
    def fill_metrics_help(metrics_dict):
        metrics_dict['dockerhub_ratelimit_current'] = f'# HELP dockerhub_ratelimit_current Current max limit for DockerHub account (or for ip address if anonymous access)\n'
        metrics_dict['dockerhub_ratelimit_current'] += f'# TYPE dockerhub_ratelimit_current gauge\n'
        metrics_dict['dockerhub_ratelimit_remaining'] = f'# HELP dockerhub_ratelimit_remaining Remaining limit for DockerHub account (or for ip address if anonymous access)\n'
        metrics_dict['dockerhub_ratelimit_remaining'] += f'# TYPE dockerhub_ratelimit_remaining gauge\n'
        metrics_dict['dockerhub_ratelimit_scrape_error'] = f'# HELP dockerhub_ratelimit_scrape_error Scrape errors (wrong status code or something else)\n'
        metrics_dict['dockerhub_ratelimit_scrape_error'] += f'# TYPE dockerhub_ratelimit_scrape_error gauge\n'
        return metrics_dict

    def fill_metrics(self, username, headers_dict, metrics_dict):
        if 'ratelimit-limit' in headers_dict and 'ratelimit-remaining' in headers_dict:
            logger.debug(f'Headers returned successfully. Configuring metrics...')
            # headers strings look like 100;w=21600. We need the first number
            ratelimit_limit = re.search('^\d*', headers_dict['ratelimit-limit']).group()
            ratelimit_remaining = re.search('^\d*', headers_dict['ratelimit-remaining']).group()
            metrics_dict['dockerhub_ratelimit_current'] += f'dockerhub_ratelimit_current{{dockerhub_user="{self.set_username(username)}"}} {ratelimit_limit}\n'
            metrics_dict['dockerhub_ratelimit_remaining'] += f'dockerhub_ratelimit_remaining{{dockerhub_user="{self.set_username(username)}"}} {ratelimit_remaining}\n'
            metrics_dict['dockerhub_ratelimit_scrape_error'] += f'dockerhub_ratelimit_scrape_error{{dockerhub_user="{self.set_username(username)}"}} 0\n'
        # not empty but without expected headers
        elif headers_dict:
            # request may not contain rate limits headers for some reasons
            # even with 200 status code so we have to check it
            logger.info(f'There aren\'t expected headers. Maybe current Docker Hub account doesn\'t have any limits. Metrics won\'t be returned')
        else:
            logger.error(f'Empty headers returned')
            metrics_dict['dockerhub_ratelimit_scrape_error'] += f'dockerhub_ratelimit_scrape_error{{dockerhub_user="{self.set_username(username)}"}} 1\n'
        return metrics_dict


# https://docs.aiohttp.org/en/stable/web_quickstart.html#handler
# A request handler must be a coroutine that accepts
# a Request instance as its only parameter...
async def metrics_handler(request):
    # ... and returns a Response instance
    return web.Response(text=request.app['metrics_str'])


async def start_background_tasks(app):
    app['rate_limits_checker'] = asyncio.create_task(Checker().entrypoint(app))


async def cleanup_background_tasks(app):
    app['rate_limits_checker'].cancel()
    await app['rate_limits_checker']


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
