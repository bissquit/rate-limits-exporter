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
                        default=os.getenv('APP_SECRETS_DIR', '/opt/secrets'),
                        type=str,
                        help='Directory with files. The name of file - username of DockerHub, file content - password. (default: /opt)')
    parser.add_argument('-p', '--port',
                        default=os.getenv("APP_PORT", 8080),
                        type=int,
                        help='Port to be listened (default: 8080)')
    parser.add_argument('-t', '--time',
                        default=os.getenv("APP_LOOP_TIME", 60),
                        type=int,
                        help='Default loop interval in seconds (default: 15)')
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
                rate_limits, tokens_dict = await self.handle_request_and_return_rate_limit(username, password, tokens_dict)
                if rate_limits.status == 200:
                    metrics_dict = self.fill_metrics(username, rate_limits.headers, metrics_dict)
                else:
                    metrics_dict['dockerhub_ratelimit_scrape_error'] += f'dockerhub_ratelimit_scrape_error{{dockerhub_user="{username}"}} 1\n'
            # I don't know workaround yet but:
            # DeprecationWarning: Changing state of started or joined application is deprecated
            app['metrics_str'] = self.get_dict_return_str_of_values(metrics_dict)
            await asyncio.sleep(app['args'].time)

    async def get_token(self, username, password):
        # Unauthenticated (anonymous) users will have the limits enforced via IP
        if username:
            auth = aiohttp.BasicAuth(login=username, password=password)
        else:
            auth = None

        async with aiohttp.ClientSession(auth=auth) as client:
            async with client.get(self.token_url) as r:
                logger.debug(f'Getting token for {self.set_username(username)} user. Request status: {r.status}')
                if r.status == 200:
                    json_body = await r.json()
                    token_str = json_body['token']
                else:
                    # we have to return token even it's an empty string
                    token_str = ''
        return token_str

    async def get_rate_limit(self, token):
        """
        :param token: bearer token to insert into header
        :return: CIMultiDictProxy object will be returned,
        read more at https://docs.aiohttp.org/en/stable/client_reference.html?highlight=multidict#response-object
        """
        headers = {'Authorization': f'Bearer {token}'}
        async with aiohttp.ClientSession(headers=headers) as client:
            # Headers will be returned on both GET and HEAD requests. Note that using GET
            # emulates a real pull and will count towards the limit; using HEAD will not
            async with client.head(self.limits_url) as r:
                logger.debug(f'Checking ratelimits. Request status: {r.status}. Request headers: {r.headers}')
        return r

    async def handle_request_and_return_rate_limit(self, username, password, tokens):
        rate_limits = ''
        for attempt in range(2):
            # get rate limits with current token
            rate_limits = await self.get_rate_limit(token=tokens[username])
            status = rate_limits.status
            # if token is old (or if it's empty string)...
            if status == 401:
                # ... then we need to renew it. We have to renew token even for Anonymous user
                tokens[username] = await self.get_token(username, password)
                # if the first attempt to renew token was unsuccessful so creds are invalid
                if attempt == 1:
                    logger.warning(f'Username/password pair of user {self.set_username(username)} is wrong!')
                continue
            elif status == 200:
                break
            else:
                logger.warning(f'Can\'t check rate limits for user {self.set_username(username)}. Status code: {status}')
        return rate_limits, tokens

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

    @staticmethod
    def fill_metrics(username, headers, metrics_dict):
        # headers strings look like 100;w=21600. We need the first number
        ratelimit_limit = re.search('^\d*', headers['ratelimit-limit']).group()
        ratelimit_remaining = re.search('^\d*', headers['ratelimit-remaining']).group()
        metrics_dict['dockerhub_ratelimit_current'] += f'dockerhub_ratelimit_current{{dockerhub_user="{username}"}} {ratelimit_limit}\n'
        metrics_dict['dockerhub_ratelimit_remaining'] += f'dockerhub_ratelimit_remaining{{dockerhub_user="{username}"}} {ratelimit_remaining}\n'
        metrics_dict['dockerhub_ratelimit_scrape_error'] = f'dockerhub_ratelimit_scrape_error{{dockerhub_user="{username}"}} 0\n'
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
    files_list = os.listdir(path=path)
    for file_name in files_list:
        full_file_path = f'{path}/{file_name}'
        logger.debug(f'Reading file {full_file_path}')
        # read file data with trailing characters removed
        file_data = open(full_file_path).read().rstrip()
        accounts_dict[file_name] = file_data
    if not accounts_dict:
        logger.debug(f'Directory {path} is empty. Skipping reading files. DockerHub limits will be checked for external ip')
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
