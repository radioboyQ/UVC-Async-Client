import asyncio
from collections import namedtuple
from pathlib import Path
from pprint import pprint
import sys
from time import sleep, strftime, gmtime

from aiohttp import ClientSession, TCPConnector, request
import click
from pypeln import asyncio_task as aio

class UVC_API_Async(object):
    """
    Class of functions for talking to the UVC device
    """

    def __init__(self, uvc_server, uvc_https_port, usrname, passwd, logger, ssl_verify=False, proxy=None, sleep_time=0.2, chunk_size=1024, max_connections=25):
        self.uvc_server = uvc_server
        self.uvc_https_port = uvc_https_port
        self.usrname = usrname
        self.passwd = passwd
        self.logger = logger
        self.ssl_verify = ssl_verify
        self.url = f"https://{uvc_server}:{uvc_https_port}"
        self.auth_cookie_name = 'JSESSIONID_AV'
        self.auth_cookie_value = None
        self.camera_mgrd_filter_name = 'cameras.isManagedFilterOn'
        self.camera_mgrd_filter_value = False
        self.apiKey = None
        self.camera_info_dict = dict()
        self.dict_info_clip = dict()
        self.sleep_time = sleep_time
        self.chunk_size = chunk_size
        self.max_connections = max_connections
        
        # Pypeln will take care of rate limiting, not AIOHttp
        connector = TCPConnector(limit=0, ttl_dns_cache=300, verify_ssl=self.ssl_verify)
        self.session = ClientSession(connector=connector, trust_env=True, headers= {'User-Agent': 'UVCAsyncLib'})

        # Build the session
        # self.session.headers = {'User-Agent': 'UVCAsyncLib'}
        if proxy is None:
            # Don't set proxy config
            self.logger.debug('Not using a proxy')
        else:
            # Set proxy param
            self.logger.debug(f'Using proxy {proxy}')
            self.session.proxies = proxy

    async def login(self):
        # Logs into UVC host
        login_payload = {'username': self.usrname, 'password': self.passwd}

        r = await self.session.post(f"{self.url}/api/2.0/login", json=login_payload)
        
        if r.status is not 200:
            data = await r.json()
            self.logger.critical(f"Failed to log into the DVR. Check the error {data}")
            sys.exit(1)
        elif r.status is 200:
            self.logger.info("Successfully logged into the DVR")
            
            # Request all the user's data
            # user_resp = await self.session.get(f"{self.url}/api/2.0/user")
            # user_data = await user_resp.json()
            user_data = await r.json()
            self.logger.debug("Obtained all user config data")
            # Get API token for the user
            for d in user_data['data']:
                if d['account']['username'] == self.usrname:
                    self.apiKey = d['apiKey']
                    self.logger.debug(f"Obtained {self.usrname}'s API key successfully")
        return r
    
    async def logout(self):
        # Logs out of UVC host

        r = await self.session.get(f"{self.url}/api/2.0/logout")
        if r.status is not 200:
            error_text = await r.text
            self.logger.critical(f"Failed to log out of the DVR. Check the error {error_text}")
            sys.exit(1)

        elif r.status is 200:
            self.logger.info("Successfully logged out the DVR")

            return r
    
    async def camera_info(self):
        """
        Obtain information about the cameras. This is the bootstrap page
        """
        camera_info = namedtuple('CameraInformation',
                                 ['camera_id', 'camera_name', 'camera_addr', 'last_rec_id', 'last_rec_start_time_epoch',
                                  'rtsp_uri', 'rtsp_enabled'])

        r = await self.session.get(f"{self.url}/api/2.0/bootstrap", cookies={'cameras.isManagedFilterOn': 'false'})
        if r.status is not 200:
            error_text = await r.text
            self.logger.critical(f'Failed to obtain the camera data. Check the error {error_text}')
            sys.exit(1)
        elif r.status is 200:
            self.logger.debug("Obtained the bootstrap page.")

        bootstrap_data = await r.json()

        # Check if anything weird is going on with the bootstrap data
        try:
            bootstrap_data['data'][0]['cameras']
        except KeyError:
            self.logger.error('The UVC didn\'t provide the bootstrap data for the cameras.')
            pprint(bootstrap_data['data'])
            sys.exit(1)
        else:
            # Check if we got all of the data from bootstrap
            if len(bootstrap_data['data'][0]['cameras']) > 0:
                self.logger.info('Obtained camera data from bootstrap endpoint')
            else:
                self.logger.critical('The bootstrap endpoint didn\'t provide the correct data. Exiting.')
                sys.exit(1)

            for c in bootstrap_data['data'][0]['cameras']:
                camera_id = c['_id']
                camera_name = c['deviceSettings']['name']
                camera_addr = c['host']
                last_rec_id = c['lastRecordingId']
                last_rec_start_time_epoch = c['lastRecordingStartTime']
                for bitrate in c['channels']:
                    if bitrate['id'] == '1':
                        rtsp_uri = bitrate['rtspUris'][1]
                        rtsp_enabled = bitrate['isRtspEnabled']
                self.camera_info_dict.update({camera_id: camera_info(camera_id, camera_name, camera_addr, last_rec_id, last_rec_start_time_epoch, rtsp_uri, rtsp_enabled)})
    
    async def clip_meta_data(self, clip_id_list):
        """
        Get the meta data for each clip ID
        - Check if
        """
        meta_cookies = {'lastMap': 'null', 'lastLiveView': 'null'}
        # meta_cookies.update(self.session.cookies)
        camera_meta_data_list = list()
        clip_id_list_len = len(clip_id_list)
        # url_id_params = str()
        clip_info = namedtuple('ClipInformation',
                                     ['clip_id', 'startTime', 'endTime', 'eventType', 'inProgress', 'locked',
                                      'cameraName', 'recordingPathId', 'fullFileName'])

        # Loop over the list and request data for each clip
        with click.progressbar(clip_id_list, length=clip_id_list_len, label='Clip Data Downloaded', show_eta=False, show_percent=False, show_pos=True) as bar:
            for id in bar:
                # Prepare the search data
                async with self.session.request('GET', f"{self.url}/api/2.0/recording/{id}", cookies=meta_cookies) as r:

                    if r.status is 200:
                        # We grabbed clip meta data, continue.
                        # self.logger.debug(f'Meta data obtained for clip {id}.')
                        json_data = await r.json()
                        camera_meta_data_list.append(json_data)
                        await asyncio.sleep(self.sleep_time)
                    elif r.status is 401:
                        self.logger.critical(f'Unauthorized, exiting.')
                        sys.exit(1)
                    else:
                        self.logger.critical(f'Unexpected error occured: {r.status}. Exiting.')
                        sys.exit(1)

        for c in camera_meta_data_list:
            # Skip clips that are in progress of recording
            c = c['data'][0]
            if c['inProgress']:
                self.logger.warning(f"Skipping clip ID {c['_id']}, it\'s still recording")
            else:
                # Clips that are done recording
                clip_id = c['_id']
                startTime = c['startTime']
                endTime = c['endTime']
                eventType = c['eventType']
                inProgress = c['inProgress']
                locked = c['locked']
                cameraName = c['meta']['cameraName']
                recordingPathId = c['meta']['recordingPathId']
                mod_cam_name = cameraName.replace(' ', '_').lower()
                human_start_time = strftime('%d_%m_%Y-%H:%M:%S',  gmtime(startTime/1000.))
                fullFileName = f"{human_start_time}-{mod_cam_name}.mp4"

                self.dict_info_clip.update({clip_id: clip_info(clip_id, startTime, endTime, eventType, inProgress, locked, cameraName, recordingPathId, fullFileName)})
                
    def camera_name(self, camera_name_list):
        """
        Function to parse out the camera's name from a given input
        """
        camera_id_list = list()
        for id in self.camera_info_dict:
            if self.camera_info_dict[id].camera_name in camera_name_list:
                # print(self.camera_info_dict[id].camera_id)
                camera_id_list.append(self.camera_info_dict[id].camera_id)
        if len(camera_id_list) is 0:
            self.logger.error("Your camera name doesn't exist. Check the spelling and try again.")
            sys.exit(1)
        else:
            return camera_id_list
    
    async def clip_search(self, epoch_start, epoch_end, camera_id_list):
        """
        Search for clips
        """
        sortBy = 'startTime'
        idsOnly = True
        sort = 'desc'
        search_headers = {'content-type': 'application/x-www-form-urlencoded'}
        # search_headers.update(self.session.headers)

        """
        /api/2.0/recording?
        cause[]=fullTimeRecording
        cause[]=motionRecording
        startTime=1538719200000
        endTime=1538805600000
        cameras[]=5b8f55509008007bce929a0f
        cameras[]=5b8f55509008007bce929a0b
        cameras[]=5b8f55509008007bce929a0d
        idsOnly=true
        sortBy=startTime
        sort=desc
        """
        search_params = [('cause[]', 'fullTimeRecording'), ('startTime', epoch_start), ('endTime', epoch_end), ('idsOnly', str(idsOnly)), ('sortBy', sortBy), ('sort', sort)]
        
        # Append list of camera IDs
        # If camera list is empty, don't do anything.
        if len(camera_id_list) is 0:
            pass
        else:
            for cam_id in camera_id_list:
                search_params.append(('cameras[]', cam_id))

        # Prepare the search data
        async with self.session.request('GET', f"{self.url}/api/2.0/recording", params=search_params, headers=search_headers) as r:
            if r.status is 200:
                self.logger.info("Searching for clips")
            elif r.status is 401:
                self.logger.critical(f'Unauthorized, exiting.')
                sys.exit(1)
            else:
                self.logger.critical(f'An error occured: {r.status}')
                sys.exit(1)

        # Get clip meta data
        data = await r.json()
        self.logger.info("Downloaded the meta data for each clip. ")
        await self.clip_meta_data(data['data'])

    async def download_footage(self, loop, max_connections, output_path= Path('downloaded_clips')):
        """
        - Search for footage & get ID values
        - Try to get the sizes for each clip
        - Download each clip on it's own
        - Name the clip and save it to disk in a folder for each camera
        """
        example = "/api/2.0/recording/5bb829e4b3a28701fe50b258/download"
        meta_cookies = {'cameras.isManagedFilterOn': 'false'}

        # Create output if it doesn't exist yet
        self.outputPathCheck(output_path)
        # Build a generator with ClipInformation types
        clip_data_generator = (self.dict_info_clip[i] for i in self.dict_info_clip)
        async with TaskPool(workers=max_connections, loop=loop) as tasks:
            for clip_information in clip_data_generator:
                await tasks.put(self.fetch(clip_information, output_path))
            
    async def fetch(self, clip_info, output_path=Path('downloaded_clips')):
        # Actually grab the file
        r = await self.session.request('GET', f"{self.url}/api/2.0/recording/{clip_info.clip_id}/download", cookies={'cameras.isManagedFilterOn': 'false'})
        self.logger.debug(f'Sending request to download clip {clip_info.clip_id}')

        if r.status is 200:
            self.logger.debug(f'Successfully requested clip {clip_info.clip_id}. Status 200')
        elif r.status is 401:
            self.logger.critical(f'Unauthorized, exiting.')
            sys.exit(1)
        else:
            self.logger.critical(f'Unexpected error occured: {r.status}. Exiting.')
            self.logger.critical(r.text)
            sys.exit(1)

        total = r.headers.get('Content-Length')
        num_chunks = round(int(total) / self.chunk_size)
        file_path = Path(output_path, clip_info.cameraName.replace(' ', '_'), clip_info.fullFileName)
        self.logger.info(f"Downloading file {clip_info.fullFileName} now.")
        if not file_path.parent.exists():
            file_path.parent.mkdir(exist_ok=True)

        with open(file_path, 'wb') as f:
            async for data in r.content.iter_chunked(1024):
                f.write(data)
        self.logger.info(f"Finished downloading file {clip_info.fullFileName}.")
        
        r.close()

    def outputPathCheck(self, output_path):
        """
        Check if the path exists
        """
        if not output_path.is_dir() and output_path.exists():
            self.logger.critical(f'Output path {output_path} is not a directory but it exists, specify a directory.')
            sys.exit(1)
        elif not output_path.exists():
            # Make the output path
            self.logger.debug('Creating output directories')
            output_path.mkdir(exist_ok=False)

        elif output_path.is_dir():
            # Don't over write existing directories, for now
            self.logger.debug('Using existing path')
            output_path.mkdir(exist_ok=True)

class TaskPool(object):
    
    def __init__(self, workers, loop):
        self._tasks = set()
        self._closed = False
        self._loop = asyncio.get_event_loop()
        self._semaphore = asyncio.Semaphore(workers)
    
    async def put(self, coro):
        if self._closed:
            raise RuntimeError("Trying put items into a closed TaskPool")
        
        await self._semaphore.acquire()
        
        task = asyncio.ensure_future(coro, loop=self._loop)
        self._tasks.add(task)
        task.add_done_callback(self._on_task_done)
    
    def _on_task_done(self, task):
        self._tasks.remove(task)
        self._semaphore.release()
    
    async def join(self):
        await asyncio.gather(*self._tasks, loop=self._loop)
        self._closed = True
    
    async def __aenter__(self):
        return self
    
    def __aexit__(self, exc_type, exc, tb):
        return self.join()