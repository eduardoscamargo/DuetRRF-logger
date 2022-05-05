#!/usr/bin/env python3
 
import time
import subprocess
import select
import paho.mqtt.client as mqtt
import datetime
import json
import os
import requests
import socket
import sys
import textwrap
import traceback
import urllib3

urllib3.disable_warnings()

def log_print(*msg, file=sys.stdout):
  print(datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S'), *msg, file=file)

# The callback for when the mqtt client receives a CONNACK response from the server.
def on_connect(client, userdata, flags, rc):
  if rc == 0:
    print("Connected successfully")
  else:
    print("Connect returned result code: " + str(rc))

class SimpleLineProtocol:
  def __init__(self, sock):
    self.socket = sock
    self.buffer = b''

  def write(self, msg):
    msg = msg.strip()
    msg += '\n'
    self.socket.sendall(msg.encode())

  def read_line(self):
    while b'\n' not in self.buffer:
      d = self.socket.recv(1024)
      if not d:
        raise socket.error()
      self.buffer = self.buffer + d

    i = self.buffer.find(b'\n')
    line = self.buffer[:i]
    self.buffer = self.buffer[i:].lstrip()
    return line

  def read_json_line(self):
    raw_lines = []
    line = b''
    while b'{' not in line and b'}' not in line:
      line = self.read_line()
      raw_lines.append(line)
    json_data = json.loads(line[line.find(b'{'):].decode())
    return json_data, raw_lines

def firmware_monitor(duet_host):
  timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')

  # create and config mqtt client
  client = mqtt.Client()
  client.on_connect = on_connect

  # enable TLS
  # client.tls_set(tls_version=mqtt.ssl.PROTOCOL_TLS)

  client.username_pw_set(os.environ['MQTT_USER'], os.environ['MQTT_PASSWORD'])
  client.connect(os.environ['MQTT_HOST'], int(os.environ['MQTT_PORT']))

  while True:
    try:
      log_print("Connecting to {}...".format(duet_host))
      sock = socket.create_connection((duet_host, 23), timeout=10)
      time.sleep(4.5)  # RepRapFirmware uses a 4-second ignore period after connecting
      conn = SimpleLineProtocol(sock)
      log_print("Connection established.")

      filename = None            # File being printed
      finishedPrint = False      # Identify when the print is done
      savedCompletionLog = False # Save only one log after print completion

      while True:
        conn.write('M408 S4')
        json_data, raw_lines = conn.read_json_line()
        status = json_data['status'] # I=idle, P=printing from SD card, S=stopped (i.e. needs a reset), C=running config file (i.e starting up), A=paused, D=pausing, R=resuming from a pause, B=busy (e.g. running a macro), F=performing firmware update

        if status == 'P':
          # a print is running, but we don't know the filename yet  
          if not filename or finishedPrint:            
            finishedPrint = False
            savedCompletionLog = False

            conn.write('M36')
            json_data, raw_lines = conn.read_json_line()
            filename = json_data['fileName']

            log_print("Print started:", filename)

          json_data['filename'] = filename
          
        elif status == 'I':
          # a previous print finished and we need to reset and wait for a new print to start
          if filename:
            finishedPrint = True
            json_data['statusFlags'] = { 'finishedPrint': finishedPrint }
            
            if not savedCompletionLog:
              log_print("Print finished, saving log...")

              savedCompletionLog = True
              log_file = open("{}_log.txt".format(timestamp),"a+")
              json_data['timestamp'] = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
              log_file.write(str(raw_lines) + '\n')
              log_file.close

        client.publish("rrf/anevo", json.dumps(json_data))

        time.sleep(1)
    except Exception as e:
      log_print('ERROR', e, file=sys.stderr)
      traceback.print_exc()
    log_print("Sleeping...", file=sys.stderr)
    time.sleep(60)

################################################################################

if __name__ == "__main__":

  if len(sys.argv) < 2:
      print(textwrap.dedent("""
        Logs RRF to a MQTT broker.

        Usage: ./rrf-mqtt.py <duet_host>

            duet_host    - DuetWifi/DuetEthernet hostname or IP address, e.g., mylog_printer.local or 192.168.1.42
          """).lstrip().rstrip(), file=sys.stderr)
      sys.exit(1)

  duet_host = sys.argv[1]

  firmware_monitor(duet_host=duet_host)