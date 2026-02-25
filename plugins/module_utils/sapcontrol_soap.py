#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Sean Freeman ,
#                      Rainer Leber <rainerleber@gmail.com> <rainer.leber@sva.de>
#                      Melvin Malagowski <mmalagowski@oxya.com>
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import os
import socket
import traceback

try:
    from urllib.request import HTTPHandler
except ImportError:
    from ansible.module_utils.urls import (
        UnixHTTPHandler as HTTPHandler,
    )

try:
    from http.client import HTTPConnection
except ImportError:
    from httplib import HTTPConnection

try:
    from suds.client import Client
    from suds.sudsobject import asdict
    from suds.transport.http import HttpAuthenticated, HttpTransport
    HAS_SUDS_LIBRARY = True
    SUDS_LIBRARY_IMPORT_ERROR = None

    class LocalSocketHttpAuthenticated(HttpAuthenticated):
        """Authenticated HTTP transport using Unix domain sockets."""
        def __init__(self, socketpath, **kwargs):
            HttpAuthenticated.__init__(self, **kwargs)
            self._socketpath = socketpath

        def u2handlers(self):
            handlers = HttpTransport.u2handlers(self)
            handlers.append(LocalSocketHandler(socketpath=self._socketpath))
            return handlers

except ImportError:
    Client = None
    asdict = None
    HttpAuthenticated = object
    HttpTransport = None
    HAS_SUDS_LIBRARY = False
    SUDS_LIBRARY_IMPORT_ERROR = traceback.format_exc()

    # Dummy class when suds is not available (keeps imports stable in tests)
    class LocalSocketHttpAuthenticated(object):
        def __init__(self, socketpath, **kwargs):
            pass

        def u2handlers(self):
            return []


class LocalSocketHttpConnection(HTTPConnection):
    """HTTP connection class that uses Unix domain sockets."""
    def __init__(self, host, port=None, timeout=socket._GLOBAL_DEFAULT_TIMEOUT,
                 source_address=None, socketpath=None):
        super(LocalSocketHttpConnection, self).__init__(host, port, timeout, source_address)
        self.socketpath = socketpath

    def connect(self):
        """Connect to Unix domain socket."""
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(self.socketpath)


class LocalSocketHandler(HTTPHandler):
    """HTTP handler for Unix domain sockets."""
    def __init__(self, debuglevel=0, socketpath=None):
        self._debuglevel = debuglevel
        self._socketpath = socketpath

    def http_open(self, req):
        return self.do_open(LocalSocketHttpConnection, req, socketpath=self._socketpath)


def recursive_dict(suds_object):
    """Convert a suds object to a plain Python dict, recursively.

    Example output: ``{'item': [{'name': 'hdbdaemon', 'value': '1'}]}``
    """
    out = {}
    if isinstance(suds_object, str):
        return suds_object
    for k, v in asdict(suds_object).items():
        if hasattr(v, '__keylist__'):
            out[k] = recursive_dict(v)
        elif isinstance(v, list):
            out[k] = []
            for item in v:
                if hasattr(item, '__keylist__'):
                    out[k].append(recursive_dict(item))
                else:
                    out[k].append(item)
        else:
            out[k] = v
    return out


def connection(service_name, hostname, port, username, password, function, parameters, sysnr, use_local):
    """
    Generic SOAP call helper.
    - Local mode currently follows sapcontrol socket convention (/tmp/.sapstream5NN13).
    - Supports dict kwargs OR single positional parameter.
    """
    if use_local and sysnr is not None:
        # Use Unix domain socket for local connection (sapcontrol-style socket)
        unix_socket = "/tmp/.sapstream5{0}13".format(str(sysnr).zfill(2))

        # Check if socket exists
        if not os.path.exists(unix_socket):
            raise Exception("SAP control Unix socket not found: {0}".format(unix_socket))

        url = "http://localhost/{0}?wsdl".format(service_name)

        try:
            localsocket = LocalSocketHttpAuthenticated(unix_socket)
            client = Client(url, transport=localsocket)
        except Exception as e:
            raise Exception("Failed to connect via Unix socket: {0}".format(str(e)))
    else:
        # Use HTTP connection (original behavior)
        url = 'http://{0}:{1}/{2}?wsdl'.format(hostname, port, service_name)
        client = Client(url, username=username, password=password)

    _function = getattr(client.service, function)
    if parameters is not None:
        if isinstance(parameters, dict):
            result = _function(**parameters)
        else:
            # support positional parameter (e.g. sap_control_exec ParameterValue)
            result = _function(parameters)
    else:
        result = _function()

    return result


def connection_sap_control(hostname, port, username, password, function, parameters,
                           sysnr=None, use_local=False, convert=True):
    """
    SAPControl wrapper.
    - Supports positional parameter (string) and kwargs (dict)
    - Applies default timeouts for StartSystem/StopSystem/RestartSystem
    - convert=True  -> returns recursive_dict(result)
      convert=False -> returns raw suds object (useful for existing modules)
    """
    # Keep positional parameter untouched (ex: ParameterValue)
    if isinstance(parameters, dict):
        auto_params = parameters.copy()
    else:
        auto_params = parameters

    # Inject default timeouts only for dict/None call styles
    if function == "StartSystem":
        if auto_params is None:
            auto_params = {"waittimeout": 0}
        elif isinstance(auto_params, dict) and "waittimeout" not in auto_params:
            auto_params["waittimeout"] = 0

    elif function in ("StopSystem", "RestartSystem"):
        if auto_params is None:
            auto_params = {"waittimeout": 0, "softtimeout": 0}
        elif isinstance(auto_params, dict):
            if "waittimeout" not in auto_params:
                auto_params["waittimeout"] = 0
            if "softtimeout" not in auto_params:
                auto_params["softtimeout"] = 0

    try:
        result = connection("sapcontrol", hostname, port, username, password, function, auto_params, sysnr, use_local)
        if convert:
            return recursive_dict(result)
        return result
    except Exception as e:
        raise Exception("Error calling SAP control function: {0}".format(str(e)))


def connection_sap_hostctrl(hostname, port, username, password, function, parameters,
                            sysnr=None, use_local=False, convert=True):
    """
    SAPHostControl wrapper.
    - Uses hostctrl local socket path (/tmp/.sapstream1128)
    - Keeps exact HostControl URL form (.../SAPHostControl/?wsdl)
    - convert=True  -> returns recursive_dict(result)
      convert=False -> returns raw suds object (useful for existing modules)
    """
    try:
        if use_local:
            # Use Unix domain socket for local hostctrl connection
            unix_socket = "/tmp/.sapstream1128"

            if not os.path.exists(unix_socket):
                raise Exception("SAP control Unix socket not found: {0}".format(unix_socket))

            url = "http://localhost/SAPHostControl/?wsdl"

            try:
                localsocket = LocalSocketHttpAuthenticated(unix_socket)
                client = Client(url, transport=localsocket)
            except Exception as e:
                raise Exception("Failed to connect via Unix socket: {0}".format(str(e)))
        else:
            url = 'http://{0}:{1}/SAPHostControl/?wsdl'.format(hostname, port)
            client = Client(url, username=username, password=password)

        _function = getattr(client.service, function)
        if parameters is not None:
            if isinstance(parameters, dict):
                result = _function(**parameters)
            else:
                result = _function(parameters)
        else:
            result = _function()

        if convert:
            return recursive_dict(result)
        return result

    except Exception as e:
        raise Exception("Error calling SAP host control function: {0}".format(str(e)))
