import click
from hydra_gams import exporter, importer, auto
from . import gdxinspector

from hydra_client.connection import JSONConnection

def hydra_app(category='import'):
    def hydra_app_decorator(func):
        func.hydra_app_category = category
        return func
    return hydra_app_decorator


def get_client(hostname, **kwargs):
    return JSONConnection(app_name='GAMS Hydra App', db_url=hostname, **kwargs)


def get_logged_in_client(context, user_id=None):
    session = context['session']
    client = get_client(context['hostname'], session_id=session, user_id=user_id)
    if client.user_id is None:
        client.login(username=context['username'], password=context['password'])
    return client


@click.group()
@click.pass_obj
@click.option('-u', '--username', type=str, default=None)
@click.option('-p', '--password', type=str, default=None)
@click.option('-h', '--hostname', type=str, default=None)
@click.option('-s', '--session', type=str, default=None)
def cli(obj, username, password, hostname, session):
    """ CLI for the GAMS-Hydra application. """

    obj['hostname'] = hostname
    obj['username'] = username
    obj['password'] = password
    obj['session']  = session

def start_cli():
    cli(obj={}, auto_envvar_prefix='HYDRA_GAMS')

@hydra_app(category='export')
@cli.command(name='export')
@click.pass_obj
@click.option('-t', '--network-id',  required=True, type=int, help='''ID of the network that will be exported.''')
@click.option('-s', '--scenario-id', required=True, type=int, help='''ID of the scenario that will be exported.''')
@click.option('-u', '--user-id', type=int, default=None)
@click.option('-o', '--output',       required=True, type=click.Path(file_okay=True, dir_okay=False), help='''Output file containing exported data''')
@click.option('-tp', '--template-id', help='''ID of the template to be used.''')
@click.option('-nn', '--node-node', is_flag=True,
              help="""(Default) Export links as 'from_name . end_name'.""")
@click.option('-ln', '--link-name', is_flag=True,
              help='''Export links as link name only.
                      If two nodes can be connected by more than one link,
                      you should choose this option.''')
@click.option('-st', '--start-date', help='''Start date of the time period used for simulation.''')
@click.option('-en', '--end-date',   help='''End date of the time period used for simulation.''')
@click.option('-dt', '--time-step',  help='''Time step used for simulation.''')
@click.option('-tx', '--time-axis', multiple=True,
              help='''Time axis for the modelling period (a list of comma separated time stamps).''')
@click.option('-et', '--export_by_type', is_flag=True,
              help='''to export data based on types, set this
                      option to 'y' or 'yes', default is export data by attributes.''')
@click.option('-gd', '--gams_date_time_index', is_flag=True,
              help='''Set the time indexes to be timestamps which are
                      compatible with gams date format (dd.mm.yyyy)''')
@click.option('--user-id', type=int, default=None)
def export(obj, network_id,scenario_id, template_id, output, node_node, link_name,start_date, end_date, time_step, time_axis, export_by_type, gams_date_time_index, user_id):


    client = get_logged_in_client(obj, user_id=user_id)

    exporter.export_network(network_id,
                            scenario_id,
                            template_id,
                            output,
                            node_node,
                            link_name,
                            start_date,
                            end_date,
                            time_step,
                            time_axis,
                            export_by_type,
                            gams_date_time_index,
                            db_url=obj['hostname'],
                            connection=client)

@hydra_app(category='import')
@cli.command(name='import')
@click.pass_obj
@click.option('-t', '--network-id', help='''ID of the network that will be exported.''')
@click.option('-s', '--scenario-id',help='''ID of the scenario that will be exported.''')
@click.option('-m', '--gms-file',   help='''Full path to the GAMS model (*.gms) used for the simulation.''')
@click.option('-f', '--gdx-file',   help='''GDX file containing GAMS results.''')
@click.option('--user-id', type=int, default=None)
def import_results(obj, network_id, scenario_id, gms_file, gdx_file, user_id):


    client = get_logged_in_client(obj, user_id=user_id)

    try:
        gdx_file = gdx_file.split(",")
    except:
        pass

    importer.import_data(network_id,
                         scenario_id,
                         gms_file,
                         gdx_file,
                         db_url=obj['hostname'],
                         connection=client)

@hydra_app(category='model')
@cli.command(name='run')
@click.pass_obj
@click.option('-t', '--network-id', help='''ID of the network that will be exported.''')
@click.option('-s', '--scenario-id', help='''ID of the scenario that will be exported.''')
@click.option('-tp', '--template-id', help='''ID of the template to be used.''', default=None)
@click.option('-m', '--gms-file', help='''Full path to the GAMS model (*.gms) used for the simulation.''')
@click.option('-o', '--output', help='''Output file containing exported data''')
@click.option('-nn', '--node-node', is_flag=True, help="""(Default) Export links as 'from_name . end_name'.""")
@click.option('-ln', '--link-name', is_flag=True, help="""Export links as link name only. If two nodes can be connected by more than one link, you should choose this option.""")
@click.option('-st', '--start-date',help='''Start date of the time period used for simulation.''')
@click.option('-en', '--end-date', help='''End date of the time period used for simulation.''')
@click.option('-dt', '--time-step',help='''Time step used for simulation.''')
@click.option('-tx', '--time-axis', multiple=True, help='''Time axis for the modelling period (a list of comma separated time stamps).''')
@click.option('-f', '--gdx-file', help='GDX file containing GAMS results.')
@click.option('-et', '--export_by_type', is_flag=True, help='''Use this switch to export data based on type, rather than attribute.''')
@click.option('-gd', '--gams_date_time_index', is_flag=True, help='Set the time indexes to be timestamps which are compatible with gams date format (dd.mm.yyyy)')
@click.option('--debug', is_flag=True, help='''Use this switch to send highly technical info and GAMS log to stdout.''')
@click.option('--user-id', type=int, default=None)
def export_run_import(obj, network_id,
                        scenario_id,
                        template_id,
                        gms_file,
                        output,
                        node_node,
                        link_name,
                        start_date,
                        end_date,
                        time_step,
                        time_axis,
                        gdx_file,
                        export_by_type,
                        gams_date_time_index,
                        debug,
                        user_id):


    client = get_logged_in_client(obj, user_id=user_id)

    auto.export_run_import(client,
                           network_id,
                            scenario_id,
                            template_id,
                            gms_file,
                            output,
                            node_node,
                            link_name,
                            start_date,
                            end_date,
                            time_step,
                            time_axis,
                            gdx_file,
                            export_by_type,
                            gams_date_time_index,
                            debug=debug,
                            db_url=obj['hostname'])

@cli.command(name='inspect')
@click.option('-f', '--filename', help='''The GDX file to inspect''')
def inspect_gdx(filename):
    gdxinspector.inspect(filename)



@cli.command()
@click.pass_obj
@click.option('--all', is_flag=True, help='By default only the Export, Run, Import is registered. This flag registers the import, export and auto apps')
def register(obj, all=False):

    auto.register()

    if all is True:
        importer.register()
        exporter.register()
