from aiohttp import ClientSession, TCPConnector
import asyncio
import logging
from pathlib import Path
from pprint import pprint

import aiomonitor
import click
import pendulum

from UVCAsyncLib.UVCAsyncLib import UVC_API_Async

# Create base logger
logger = logging.getLogger("UVC-DVR-Downloader")

CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])

async def sub_main(ctx, start_time, end_time, username, hostname, port, output_dir, password, camera_names, timezone, max_connections, dry_run, logger, debug, loop):
    """
    Main function but is asynchronous
    """
    
    """
    Plan:
    - Log into UVC
    - Get Camera information
    - Search for block of videos
    - Download videos
    """
    
    # Start time conversion
    denver_start = pendulum.from_format(start_time, 'DD-MM-YYYY:HH:mm:ss', tz=timezone)
    utc_start = denver_start.in_tz('UTC')
    # Convert the datetime object to JavaScript Epoch time
    utc_start_epoch = utc_start.int_timestamp * 1000
    
    # End time conversion
    denver_end = pendulum.from_format(end_time, 'DD-MM-YYYY:HH:mm:ss', tz=timezone)
    utc_end = denver_end.in_tz('UTC')
    # Convert the datetime object to JavaScript Epoch time
    utc_end_epoch = utc_end.int_timestamp * 1000
    
    client = UVC_API_Async(hostname, port, username, password, logger, sleep_time=0)  # , proxy=proxy)
    
    raw_resp = await client.login()
    
    raw_resp = await client.camera_info()
    
    camera_id_list = client.camera_name(camera_names)
    
    await client.clip_search(epoch_start=utc_start_epoch, epoch_end=utc_end_epoch, camera_id_list=camera_id_list)
    
    if dry_run:
        logger.critical("This is a DRY RUN. No videos were downloaded.")
        logger.info(f"This query would have downloaded {len(client.dict_info_clip)} videos.")
    else:
        logger.debug("Not a dry run. All is normal.")
        await client.download_footage(loop, max_connections, Path(output_dir))
    
    raw_resp = await client.logout()
    await client.session.close()
    
def datetime_check(ctx, param, value):
    """
    Function to check the datetime input
    """
    if value is None:
        if param.name is 'start_time':
            raise click.BadParameter('You must provide a start time.')
        elif param.name is 'end_time':
            raise click.BadParameter('You must provide an end time.')
        else:
            raise click.BadParameter(f'I\'m being called for {param.name} which is wrong.')
    try:
        # Dummy conversion. Just checking syntax now. Real conversion happens in main.
        denver_dt = pendulum.from_format(value, 'DD-MM-YYYY:HH:mm:ss')
        return value
    except:
        if param.name is 'start_time':
            raise click.BadParameter('Start datetime is not in the correct format.')
        elif param.name is 'end_time':
            raise click.BadParameter('End datetime is not in the correct format.')
        else:
            raise click.BadParameter(f'I\'m being called for {param.name} which is wrong.')

def timezone_check(ctx, param, value):
    """
    Check if the supplied timezone is valid
    """
    if value in pendulum.timezones:
        return value
    elif value is not None:
        for tz in pendulum.timezones:
            if tz.endswith(value):
                return tz
    else:
        click.echo("Try one of these timezones: \n")
        for tz in pendulum.timezones:
            click.echo(tz)
        if value is None:
            raise click.BadParameter('Use one of the above timezones that matches where you are and try again.')
        else:
            raise click.BadParameter(f'The timezone {value} isn\'t valid, try again.')


@click.command(name='download-videos', context_settings=CONTEXT_SETTINGS)
@click.option('-s', '--start-time', callback=datetime_check, help='Specify a start time in DD-MM-YYYY:HH:mm:ss')
@click.option('-e', '--end-time', callback=datetime_check, help='Specify a start time in DD-MM-YYYY:HH:mm:ss')
@click.option('-u', '--username', help='Unifi Video username', required=True, default='administrator', type=click.STRING)
@click.option('-d', '--hostname', help='Domain name, hostname or IP address for the Video controller. E.g. 127.0.0.1', type=click.STRING, required=True)
@click.option('-p', '--port', help='Port number for the Video controller. Defaults to 7443', default=7443, type=click.IntRange(1, 65535))
@click.option('-o', '--output-dir', help='Directory to save the videos to.', type=click.Path(exists=False, file_okay=False, writable=True, resolve_path=True, allow_dash=True))
@click.option('--password', help='UVC User\'s password. Script will prompt for password later on if not entered. This option exists for scripting.', prompt=True, hide_input=True)
@click.option('-tz', '--timezone', callback=timezone_check, help='Set timezone to be something other than \'America/Denver\'. Default is \'America/Denver\'.', default='America/Denver', type=click.STRING)
@click.option('-m', '--max-connections', help='Maximum connections to have open at once downloading files. Default is 4.', type=click.IntRange(1, 1000), default=4)
@click.option('--debug', help="Show debug logs and start AIOMonitor. ", default=False, is_flag=True)
@click.option('-v', '--verbose', help="Show more information than normal. ", default=False, is_flag=True)
@click.option('-q', '--quiet', help="Show less information than normal. ", default=False, is_flag=True)
@click.option('-n','--dry-run', help="Don't download videos, just get a list that *would* be downloaded.", default=False, is_flag=True)
@click.argument('camera-names', nargs=-1)
@click.pass_context
def main(ctx, start_time, end_time, username, hostname, port, output_dir, password, camera_names, timezone, max_connections, dry_run, debug, verbose, quiet):
    """Download videos for cameras for a specific time frame.

    Times default to America/Denver."""
    # Set up logging
    
    if debug:
        console_log_level = logging.DEBUG
    elif verbose:
        console_log_level = logging.INFO
    elif quiet:
        console_log_level = logging.ERROR
    else:
        console_log_level = logging.WARN

    # Base logger
    logger.setLevel(logging.DEBUG)

    # Create console handler with a higher log level
    ch = logging.StreamHandler()
    ch.setLevel(console_log_level)

    # Create log format
    formatter = logging.Formatter('%(name)s - %(levelname)s - %(message)s')

    # Set the format
    ch.setFormatter(formatter)

    # Add console handler to main logger
    logger.addHandler(ch)
    
    # Drop into an event loop
    loop = asyncio.get_event_loop()
    if debug:
        logger.debug("Debug mode enabled. Use Netcat or Telnet to connect to 127.0.0.1 port 50101 for AIO internal information. This uses the library 'aiomonitor'.")
        with aiomonitor.start_monitor(loop=loop):
            loop.run_until_complete(sub_main(ctx, start_time, end_time, username, hostname, port, output_dir, password, camera_names, timezone, max_connections, dry_run, logger, debug, loop))
    else:
        loop.run_until_complete(sub_main(ctx, start_time, end_time, username, hostname, port, output_dir, password, camera_names, timezone, max_connections, dry_run, logger, debug, loop))

if __name__ == "__main__":
    main()
    