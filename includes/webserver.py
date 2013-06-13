#!/usr/bin/env python
# -*- coding: utf-8 -*-
import logging
import json
import glob
import os
import random
import string
import sys
from flask import Flask, request, Response, abort
from functools import wraps
from sqlalchemy import create_engine, MetaData, Table, Column, String,\
                   select, and_, Integer
from collections import deque
from sqlalchemy.exc import *
from webserverOptions import *
import includes.common

os.chdir(os.path.dirname(os.path.realpath(__file__)))
os.chdir('..')

logging.basicConfig(level=logging.DEBUG, filename='/tmp/snoopy_server.log',
                format='%(asctime)s %(levelname)s %(filename)s: %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S')

#logging.basicConfig()
#logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)

logging.debug("Loading webserver code")

app = Flask(__name__)
db = create_engine(dbms)
metadata = MetaData(db)
metadata.reflect()

drone_tbl_def = Table('drones', MetaData(),
                        Column('drone', String(40), primary_key=True),
                        Column('key', String(40)))

def manage_drone_account(drone, operation):

    #if not db.dialect.has_table(db.connect(), 'drones'):
    if 'drones' not in metadata.tables.keys():
        db.create(drone_tbl_def )
    metadata.reflect()
    drone_table = metadata.tables['drones']

    if operation == "create":
        try:
            key = ''.join(random.choice(string.ascii_uppercase + string.digits)
                          for x in range(15))
            drone_table.insert().execute(drone=drone, key=key)
            #drone_table.insert().prefix_with("OR REPLACE")\
            #    .execute(drone=drone, key=key)
        except IntegrityError:
            logging.error("Drone '%s' already exists!" %drone) #REPLACE INTO will actually just replace it
            sys.exit(-1)
        except Exception:
            logging.exception("Exception whilst attempting to add drone")
        else:
            return key
    elif operation == "delete":
        db.execute("DELETE FROM drones WHERE drone='{0}'".format(drone))
        #drone_table.delete().execute(drone=drone)
        return True
    elif operation == "list":
        return(drone_table.select().execute().fetchall())
    else:
        logging.error("Bad operation '%s' passed to manage_drone_account" %
                      operation)
        return False

def write_local_db(rawdata):
    """Write server db"""
    for entry in rawdata:
        tbl = entry['table']
        data = entry['data']
        if tbl not in metadata.tables.keys():
            logging.error("Error: Drone attempting to insert data into invalid table '%s'"%tbl)
            return False
        tbl=metadata.tables[tbl]
        try:
            tbl.insert().execute(data)
        except Exception,e:
             logging.exception(e)
             return False
    return True

def verify_admin(user, pwd):
    if user == "potato" and pwd == "fl0atb0at":
        return True

def verify_account(_drone, _key):
    try:
        drone_table=metadata.tables['drones']
        s = select([drone_table],

                   and_(drone_table.c.drone==_drone, drone_table.c.key==_key))
        result = db.execute(s).fetchone()

        if result:
            logging.debug("Auth granted for %s" % _drone)
            return True
        else:
            logging.debug("Access denied for %s" % _drone)
            return False
    except Exception, e:
        logging.exception('Error: %s' %str(e))
        return False

def authenticate():
    """Sends a 401 response that enables basic auth"""
    return Response(
    'Could not verify your access level for that URL.\n'
    'You have to login with proper credentials', 401,
    {'WWW-Authenticate': 'Basic realm="Login Required"'})

def requires_admin_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not verify_admin(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated


def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not verify_account(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated

def unpack_data(request):
    if request.headers['Content-Type'] == 'application/json':
       try:
           return json.loads(request.data)
       except Exception,e:
           logging.error(e)


#
pendingCommands = {}
newResponses = {}

@app.route('/cmd/droneResponse')
@requires_auth
def drone_response():
    drone = auth = request.authorization.username
    if 'command' not in request.args or 'output' not in request.args:
        abort(400)
    else:
        command, output = request.args['command'], request.args['output']
        if drone not in newResponses:
            newResponses[drone] = deque([(command,output)])
        else:
            newResponses[drone].append((command,output))
        logging.info(newResponses)
        return "Thank you, kind sir."

@app.route('/cmd/droneQuery')
@requires_auth
def drone_query():
    _drone = auth = request.authorization.username
    if _drone in pendingCommands and pendingCommands[_drone]:
        return pendingCommands[_drone].popleft()
    else:
        return ""

@app.route('/cmd/serverGetResponse')
@requires_admin_auth
def server_get_response():
    if 'drone' not in request.args:
        return "Please specify 'drone' parameter"
    else:
        drone = request.args['drone']
        if drone in newResponses and newResponses[drone]:
            command, output = newResponses[drone].popleft()
            resp = "[%s] %s\n%s" %(drone, command, output)
            return Response(resp, mimetype="text/plain")
        else:
            return ""

@app.route('/cmd/serverAddCommand')
@requires_admin_auth
def server_add_command():
    if 'command' not in request.args or 'drone' not in request.args:
        return "Please specify 'command' and 'drone' parameters"
    else:
        command, drone = request.args['command'], request.args['drone']
        if drone not in pendingCommands:
            pendingCommands[drone] = deque([command])
        else:
            pendingCommands[drone].append(command)
        logging.info(pendingCommands)
        return "Sending command '%s' to '%s'" % (command, drone)


# For the collection of data
@app.route(path, methods=['POST'])
@requires_auth
def catch_data():
    try:
        jsdata = unpack_data(request)
    except Exception,e:
        logging.error("Unable to parse JSON from '%s'" % request)
    else:
    #if jsdata:
        result = write_local_db(jsdata)

        if result:
            return '{"result":"success", "reason":"None"}'
        else:
            return '{"result":"failure", "reason":"Check server logs"}'

def create_db_tables():

    logging.debug("Creating tables")
    ident_tables = []
    moduleNames = [ "plugins." + os.path.basename(f)[:-3]
                    for f in glob.glob("./plugins/*.py")
                    if not os.path.basename(f).startswith('__') \
                        and not os.path.basename(f).startswith(__file__) ]
    tbls = []
    tbls.append(drone_tbl_def)

    for mod in moduleNames:
        logging.debug("Loading tables for %s" % mod)
        m = __import__(mod, fromlist="Snoop").Snoop()
        for ident in m.get_ident_tables():
            if ident is not None:
                ident_tables.append(ident)

        tmptables = m.get_tables()
        for t in tmptables:
            tbls.append(t)

    for tbl in tbls:
        tbl.metadata = metadata
        if tbl.name in ident_tables:
            tbl.append_column( Column('drone',String(length=20)) )
            tbl.append_column( Column('location', String(length=60)) )
            tbl.append_column( Column('run_id', String(length=11)) )
        if tbl.name not in metadata.tables.keys():
            logging.debug("Creating table %s" % tbl.name)
            tbl.create()
            metadata.reflect()


def run_webserver():
    create_db_tables()
    app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    run_webserver()
