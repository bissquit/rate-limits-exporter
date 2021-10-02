import os
import sys
import json
import aiohttp
from aiohttp import web
import asyncio
import logging
import argparse
import multidict

logging.basicConfig(level=os.getenv("LOG_LEVEL", logging.DEBUG), format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

metrics = """
# HELP dockerhub_ratelimit_current Current max limit for DockerHub account (or for ip address if anonymous access)
# TYPE dockerhub_ratelimit_current gauge
dockerhub_ratelimit_current 0
# HELP dockerhub_ratelimit_current Remaining limit for DockerHub account (or for ip address if anonymous access)
# TYPE dockerhub_ratelimit_current gauge
dockerhub_ratelimit_remaining 0
"""
# metrics = {
#     'dockerhub_ratelimit_current': '',
#     'dockerhub_ratelimit_remaining': ''
# }


def parse_args():
    parser = argparse.ArgumentParser(prog='rate_limits_exporter', description='Docker HUB ratelimits exporter for Prometheus')
    parser.add_argument('-d', '--directory', default='/tmp/dockerhub-users', type=str, help='Directory with files. The name of file - username of DockerHub, file content - password. (default: /opt)')
    parser.add_argument('-p', '--port', default=8080, type=int, help='Port to be listened (default: 8080)')
    return parser.parse_args()


class Checker:
    def __init__(self, username, password):
        self.username = username
        self.password = password
        self.token_url = "https://auth.docker.io/token?service=registry.docker.io&scope=repository:ratelimitpreview/test:pull"
        self.limits_url = "https://registry-1.docker.io/v2/ratelimitpreview/test/manifests/latest"

    async def entrypoint(self, loop_interval):
        token = ''
        while True:

            for attempt in range(2):
                rate_limits = await self.get_rate_limit(token=token)
                status = rate_limits.status
                if status == 401:
                    token = await self.get_token(username=self.username, password=self.password)
                    if attempt == 2:
                        logger.warning('Username/password pair is wrong!')
                    continue
                elif status == 200:
                    break
                else:
                    logger.warning(f'Can\'t check ratelimits. Status code: {status}')

            await asyncio.sleep(loop_interval)

    async def get_token(self, username, password):
        # Unauthenticated (anonymous) users will have the limits enforced via IP
        if username:
            auth = aiohttp.BasicAuth(login=username, password=password)
        else:
            auth = None

        async with aiohttp.ClientSession(auth=auth) as client:
            async with client.get(self.token_url) as r:
                logger.debug(f'Getting token. Request status: {r.status}')
                # assert r.status == 200
                json_body = await r.json()
        return json_body['token']

    async def get_rate_limit(self, token):
        """
        :param token: bearer token to insert into header
        :return: CIMultiDictProxy object will be returned,
        read more at https://docs.aiohttp.org/en/stable/client_reference.html?highlight=multidict#response-object
        """
        headers = {'Authorization': f'Bearer {token}'}
        async with aiohttp.ClientSession(headers=headers) as client:
            # Headers will be returned on both GET and HEAD requests.
            # Note that using GET emulates a real pull and will count
            # towards the limit; using HEAD will not
            async with client.head(self.limits_url) as r:
                logger.debug(f'Checking ratelimits. Request status: {r.status}. Request headers: {r.headers}')
                # assert r.status == 200
        return r

    # async def handle_request_and_return_rate_limit(self, username, password):
    #     for attempt in range(2):
    #         rate_limits = await self.get_rate_limit(token=token)
    #         status = rate_limits.status
    #         if status == 401:
    #             token = await self.get_token(username=self.username, password=self.password)
    #             if attempt == 2:
    #                 logger.warning('Username/password pair is wrong!')
    #             continue
    #         elif status == 200:
    #             break
    #         else:
    #             logger.warning(f'Can\'t check ratelimits. Status code: {status}')


class Metrics:
    # def __init__(self):
    #     pass

    # https://docs.aiohttp.org/en/stable/web_quickstart.html#handler
    # A request handler must be a coroutine that accepts
    # a Request instance as its only parameter...
    async def handler(self, request):
        global metrics
        # ... and returns a Response instance
        return web.Response(text=metrics)


# https://docs.aiohttp.org/en/stable/web_advanced.html#background-tasks
async def start_background_tasks(app):
    app['rate_limits_checker'] = asyncio.create_task(Checker("", "").entrypoint(15))


async def cleanup_background_tasks(app):
    app['rate_limits_checker'].cancel()
    await app['rate_limits_checker']


def read_files_with_secrets(path):
    """
    :param path: each filename in the directory is a DockerHub account name. File data is a password
    :return: dict with username : password pairs or empty dict if directory is empty
    """
    accounts = {}
    files = os.listdir(path=path)
    for file in files:
        full_file_path = f'{path}/{file}'
        logger.debug(f'Reading file {full_file_path}')
        # read file data with trailing characters removed
        file_data = open(full_file_path).read().rstrip()
        accounts[file] = file_data
    if not accounts:
        logger.debug(f'Directory {path} is empty')
    return accounts


def main():
    args = parse_args()
    accounts = read_files_with_secrets(args.directory)
    # print(accounts)
    app = web.Application()
    app.add_routes([web.get('/metrics', Metrics().handler)])
    app.on_startup.append(start_background_tasks)
    app.on_cleanup.append(cleanup_background_tasks)
    web.run_app(app, port=args.port)


if __name__ == "__main__":
    main()