""" 

Wyze Sense 2 MQTT
v0.2.1

"""

import paho.mqtt.client as mqtt
import json
import socket
import sys
import logging
import logging.config
import logging.handlers
import subprocess
from retrying import retry
from wyzesense_custom import *

# Read configuration file
CONFIG_FILE = "config/config.json"
def read_config():
    with open(CONFIG_FILE) as config_file:
        data = json.load(config_file)
    return data
config = read_config()

# Set Config File Variables
MQTT_HOST = config["mqtt"]["host"]
MQTT_PORT = config["mqtt"]["port"]
MQTT_USERNAME = config["mqtt"]["username"]
MQTT_PASSWORD = config["mqtt"]["password"]
MQTT_CLIENT_ID = config["mqtt"]["client_id"]
MQTT_CLEAN_SESSION = config["mqtt"]["clean_session"]
MQTT_KEEPALIVE = config["mqtt"]["keepalive"]
MQTT_QOS = config["mqtt"]["qos"]
MQTT_RETAIN = config["mqtt"]["retain"]
PERFORM_HASS_DISCOVERY = config["perform_hass_discovery"]
HASS_TOPIC_ROOT = config["hass_topic_root"]
WYZESENSE2MQTT_TOPIC_ROOT = config["wyzesense2mqtt_topic_root"]
USB_DEVICE = config["usb_device"]
LOG_FILENAME = config["log_filename"]

# Set MQTT Topics
SCAN_TOPIC = WYZESENSE2MQTT_TOPIC_ROOT + "scan"
SCAN_RESULT_TOPIC = WYZESENSE2MQTT_TOPIC_ROOT + "scan_result"
REMOVE_TOPIC = WYZESENSE2MQTT_TOPIC_ROOT + "remove"

diff = lambda l1, l2: [x for x in l1 if x not in l2]

def init_logging():
    LOGGING = {
        'version': 1,
        'formatters': {
            'verbose': {
                'format': '%(asctime)s %(levelname)-8s %(name)-15s %(message)s',
                'datefmt': '%Y-%m-%d %H:%M:%S'
            },
            'simple': {
                'format': '%(message)s'
            }
        },
        'handlers': {
            'file':{
                'class': 'logging.handlers.TimedRotatingFileHandler',
                'level': 'INFO',
                'formatter': 'verbose',
                'filename': LOG_FILENAME,
                'when': 'midnight',
                'backupCount': 7,
                'encoding': 'utf-8'
            },
            'console': {
                'class': 'logging.StreamHandler',
                'level': 'DEBUG',
                'formatter': 'simple'
            }
        },
        'root': {
            'handlers': ['file', 'console'],
            'level': 'DEBUG'
        }
    }
    logging.config.dictConfig(LOGGING)
    global _LOGGER
    _LOGGER = logging.getLogger("__name__")

def findDongle():
    df = subprocess.check_output(["ls", "-la", "/sys/class/hidraw"]).decode('utf-8').lower()
    for l in df.split('\n'):
        if ("e024" in l and "1a86" in l):
            for w in l.split(' '):
                if ("hidraw" in w):
                    return "/dev/%s" % w

def on_connect(client, userdata, flags, rc):
    _LOGGER.info("Connected with result code " + str(rc))
    client.subscribe([(SCAN_TOPIC, MQTT_QOS), (REMOVE_TOPIC, MQTT_QOS)])
    client.message_callback_add(SCAN_TOPIC, on_message_scan)
    client.message_callback_add(REMOVE_TOPIC, on_message_remove)

def on_disconnect(client, userdata, rc):
    _LOGGER.info("Disconnected with result code " + str(rc))
    client.message_callback_remove(SCAN_TOPIC)
    client.message_callback_remove(REMOVE_TOPIC)

# Process messages
def on_message(client, userdata, msg):
    _LOGGER.info(msg.topic+" " + str(msg.payload))  

# Process message to scan for new devices
def on_message_scan(client, userdata, msg):
    _LOGGER.info("In on_message_scan: {0}".format(msg.payload.decode()))
    prescan_result = ws.List()
    _LOGGER.debug("Result of prescan {0}".format(prescan_result))   

    ws.Scan()

    postscan_result = ws.List()
    _LOGGER.debug("Result of postscan {0}".format(postscan_result))  

    s = diff(postscan_result, prescan_result)  
    _LOGGER.info("Diff is {0}".format(s))  

    if s != []:
        jsonData = json.dumps({"macs": s})
        _LOGGER.debug(jsonData)
        client.publish(SCAN_RESULT_TOPIC, payload = jsonData)
    else:
        _LOGGER.debug("Empty Scan")

# Process message to remove device
def on_message_remove(client, userdata, msg):
    _LOGGER.info("In on_message_remove: {0}".format(msg.payload.decode()))
    sensor_mac = msg.payload

    ws.Delete(sensor_mac)

    clear_retained_mqtt_topics(sensor_mac)

# Send HASS discovery topics to MQTT
def send_discovery_topics(sensor_mac, sensor_type):
    _LOGGER.info("Publishing discovery topics")
    device_payload = {
        "identifiers": ["wyzesense_{0}".format(sensor_mac), sensor_mac],
        "manufacturer": "Wyze",
        "model": "Motion Sensor" if sensor_type == "motion" else "Contact Sensor",
        "name": "Wyze Sense Motion Sensor" if sensor_type == "motion" else "Wyze Sense Contact Sensor"
    }

    binary_sensor_payload = {
        "state_topic": WYZESENSE2MQTT_TOPIC_ROOT+sensor_mac,
        "name": "Wyze Sense {0}".format(sensor_mac),
        "payload_on": "1",
        "payload_off": "0",
        "json_attributes_topic": WYZESENSE2MQTT_TOPIC_ROOT+sensor_mac,
        "value_template": "{{ value_json.state }}",
        "unique_id": "wyzesense_{0}".format(sensor_mac),
        "device_class": "motion" if sensor_type == "motion" else "opening",
        "device": device_payload
    }
    _LOGGER.debug(binary_sensor_payload)
    binary_sensor_topic = HASS_TOPIC_ROOT+"binary_sensor/wyzesense_{0}/config".format(sensor_mac)
    client.publish(binary_sensor_topic, payload = json.dumps(binary_sensor_payload), qos = MQTT_QOS, retain = MQTT_RETAIN)

    signal_strength_sensor_payload = {
        "state_topic": WYZESENSE2MQTT_TOPIC_ROOT+sensor_mac,
        "name": "Wyze Sense {0} Signal Strength".format(sensor_mac),
        "unit_of_measurement": "dBm",
        "value_template": "{{ value_json.signal_strength }}",
        "unique_id": "wyzesense_{0}_signal_strength".format(sensor_mac),
        "device_class": "signal_strength",
        "device": device_payload
    }
    _LOGGER.debug(signal_strength_sensor_payload)
    signal_strength_sensor_topic = HASS_TOPIC_ROOT+"sensor/wyzesense_{0}_signal_strength/config".format(sensor_mac)
    client.publish(signal_strength_sensor_topic, payload = json.dumps(signal_strength_sensor_payload), qos = MQTT_QOS, retain = MQTT_RETAIN)

    battery_sensor_payload = {
        "state_topic": WYZESENSE2MQTT_TOPIC_ROOT+sensor_mac,
        "name": "Wyze Sense {0} Battery".format(sensor_mac),
        "unit_of_measurement": "%",
        "value_template": "{{ value_json.battery_level }}",
        "unique_id": "wyzesense_{0}_battery".format(sensor_mac),
        "device_class": "battery",
        "device": device_payload
    }
    _LOGGER.debug(battery_sensor_payload)
    battery_sensor_topic = HASS_TOPIC_ROOT+"sensor/wyzesense_{0}_battery/config".format(sensor_mac)
    client.publish(battery_sensor_topic, payload = json.dumps(battery_sensor_payload), qos = MQTT_QOS, retain = MQTT_RETAIN)

# Clear any retained topics in MQTT
def clear_retained_mqtt_topics(sensor_mac):
    _LOGGER.info("Clearing device topics")
    event_topic = WYZESENSE2MQTT_TOPIC_ROOT+"{0}".format(event.MAC)
    client.publish(event_topic, payload = None, qos = MQTT_QOS, retain = MQTT_RETAIN)

    binary_sensor_topic = HASS_TOPIC_ROOT+"binary_sensor/wyzesense_{0}/config".format(sensor_mac)
    client.publish(binary_sensor_topic, payload = None, qos = MQTT_QOS, retain = MQTT_RETAIN)

    signal_strength_sensor_topic = HASS_TOPIC_ROOT+"sensor/wyzesense_{0}_signal_strength/config".format(sensor_mac)
    client.publish(signal_strength_sensor_topic, payload = None, qos = MQTT_QOS, retain = MQTT_RETAIN)

    battery_sensor_topic = HASS_TOPIC_ROOT+"sensor/wyzesense_{0}_battery/config".format(sensor_mac)
    client.publish(battery_sensor_topic, payload = None, qos = MQTT_QOS, retain = MQTT_RETAIN)

def on_event(ws, event):
    _LOGGER.info("Processing Event")
    _LOGGER.debug("Event data: {0}".format(event))
    if event.Type == 'state':
        try:
            (sensor_type, sensor_state, sensor_battery, sensor_signal) = event.Data
            event_payload = {
                "available": True,
                "mac": event.MAC,
                "state": 1 if sensor_state == "open" or sensor_state == "active" else 0,
                "device_class": "motion" if sensor_type == "motion" else "opening",
                "device_class_timestamp": event.Timestamp.isoformat(),
                "signal_strength": sensor_signal * -1,
                "battery_level": sensor_battery
            }

            _LOGGER.debug(event_payload)

            event_topic = WYZESENSE2MQTT_TOPIC_ROOT+"{0}".format(event.MAC)
            client.publish(event_topic, payload = json.dumps(event_payload), qos = MQTT_QOS, retain = MQTT_RETAIN)

            if PERFORM_HASS_DISCOVERY == True:
                send_discovery_topics(event.MAC, sensor_type)

        except TimeoutError as err:
            _LOGGER.error(err)
        except socket.timeout as err:            
            _LOGGER.error(err)
        except: # catch *all* exceptions
            e = sys.exc_info()[0]
            _LOGGER.error("Error: {0}".format(e))

@retry(wait_exponential_multiplier=1000, wait_exponential_max=10000)
def beginConn():
    return Open(USB_DEVICE, on_event)

# Initialize Logging
init_logging()

#Connect to USB dongle
if USB_DEVICE.lower() == 'auto': 
    USB_DEVICE = findDongle()
_LOGGER.info("Attempting to open connection to hub at {0}".format(USB_DEVICE))
ws = beginConn()

# Configure MQTT Client
client = mqtt.Client(client_id = MQTT_CLIENT_ID, clean_session = MQTT_CLEAN_SESSION)
client.username_pw_set(username = MQTT_USERNAME, password = MQTT_PASSWORD)
client.reconnect_delay_set(min_delay=1, max_delay=120)
client.on_connect = on_connect
client.on_disconnect = on_disconnect
client.on_message = on_message

# Connect to MQTT and maintain connection
_LOGGER.info("Attempting to open connection to MQTT host {0}".format(MQTT_HOST))
client.connect(MQTT_HOST, port = MQTT_PORT, keepalive = MQTT_KEEPALIVE)
client.loop_forever(retry_first_connection = True)