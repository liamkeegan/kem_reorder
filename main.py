#####################################################################
# Cisco CUCM KEM Reorderer
# Use: Plug in a SEP device name and it'll reorder the BLF/SD entries
# Why: Because reordering KEMs manually or through BAT freaking sucks
# By: Liam Keegan / lkeegan@247networks.com / @liamjkeegan
# Ver: 1.0
#####################################################################

# Import the relevant libraries
# You need zeep, requests, lxml and their dependencies
from zeep import Client
from zeep import helpers
from zeep.cache import SqliteCache
from zeep.transports import Transport
from zeep.exceptions import Fault
from zeep.plugins import HistoryPlugin
from requests import Session
from requests.auth import HTTPBasicAuth
from urllib3 import disable_warnings
from urllib3.exceptions import InsecureRequestWarning
from lxml import etree
import json
import getpass
 
# VARIABLE SECTION
# Capture username, password and server information

username = input('Administrator Username: ')
password = getpass.getpass(prompt='Administrator Password: ')
 
# If you're not disabling SSL verification, host should be the FQDN of the server rather than IP
host = input('CUCM Host: ')
 
# Setup the Zeep connection, create the service and get ready to
disable_warnings(InsecureRequestWarning)
 
# You need the WSDL file from the CUCM named AXLAPI.wsdl. You download this from CCMAdmin->Plugins, and then put it the same folder
wsdl = 'AXLAPI.wsdl'
location = f'https://{host}:8443/axl/'
binding = "{http://www.cisco.com/AXLAPIService/}AXLAPIBinding"
 
# Create a custom session to disable Certificate verification.
# In production you shouldn't do this,
# but for testing it saves having to have the certificate in the trusted store.
session = Session()
session.verify = False
session.auth = HTTPBasicAuth(username, password)
 
transport = Transport(cache=SqliteCache(), session=session, timeout=20)
history = HistoryPlugin()
client = Client(wsdl=wsdl, transport=transport, plugins=[history])
service = client.create_service(binding, location)
 
def show_history():
    for item in [history.last_sent, history.last_received]:
        print(etree.tostring(item["envelope"], encoding="unicode", pretty_print=True))
 
 
# Collect the Device Name of the IP phone. Device names start with SEP and the MAC, so they need to be 15 digits.
# Sets up a 'while True' loop that repeats until the loop is broken. This allows us to retry if something isn't right.
 
while True:
    # Collects the Device Name, and assigns it to the phone_name variable
    phone_name = input('Enter the device name (including SEP) to sort: ')
 
    # If the length of phone_name isn't 15 characters, fail and try again.
    if len(phone_name) != 15:
        print("INVALID: Enter the phone name as a 15-character string ('SEP<MAC>')")
        continue
    # If it doesn't start with SEP, fail and try again.
    if not phone_name.startswith('SEP'):
        print("INVALID: Phone name must start with SEP.")
        continue
    else:
        # If we get an initially valid (starts with SEP and has 15 characters) device name, send it to CUCM to see if it's a valid number
        try:
            # We have a maybe-valid device name, so let's get it from CUCM.
            resp = service.getPhone(name=phone_name)
            # We'll take the response (assuming that it's successful) and strip off the 'return' key, leaving just the payload
            phone_data = resp['return'].phone
            # Let's make sure this device actually has BLFs. if not, fail and try again.
            if phone_data['busyLampFields'] == None:
                print("Phone must have BLFs to sort. Please try again.")
                continue
            # Otherwise, break out of this loop and move on.
            break
        except Fault:
            print('FAILED:')
            show_history()
            continue
 
# Turn the phone_data into a Python-native dictionary so we can pop elements out of it.
# There's probably a way better way to do this, but I have no idea how.
temp_phone_data = helpers.serialize_object(phone_data['busyLampFields'], dict)
 
# Start the iteration through the items in the busyLampField list.
for blf in temp_phone_data['busyLampField']:
    # Remove the old index, since we don't need that anymore
    blf.pop('index', None)
    # If there aren't any associatedBlfSdFeatures, remove the key
    if blf['associatedBlfSdFeatures'] == None:
        blf.pop('associatedBlfSdFeatures', None)
    # If the blfDest is empty, remove it. You can either have blfDest OR blfDirn+routePartition, but not both.
    # ** THERE IS AN ERROR IN THE WSDL FILE - blfDest needs to be changed from max 1 to max 0.
    # If you get key errors from Zeep, that's the problem.
    if blf['blfDest'] == None:
        blf.pop('blfDest', None)
    else:
        blf.pop('blfDirn', None)
        blf.pop('routePartition', None)
 
# Sort the data into a new list called sortedBlf, using the label as the sort key
sortedBlf = sorted(temp_phone_data['busyLampField'], key = lambda i: i['label'].lower())
 
# Once the list is sorted, go back in and add a new index key based on the new sort order. The enumerate function returns the index that can be referenced. We add +1 since it starts at 0.
for index,blf in enumerate(sortedBlf):
    blf['index'] = index+1
 
# Create a new empty dictionary called new_phone_data
new_phone_data = {}
# Add the Device Name (SEP+MAC) into the dict as the 'name' key. This tells CUCM what phone to apply the changes to.
new_phone_data['name'] = phone_data.name
# Create an empty dict called busyLampFields
new_phone_data['busyLampFields']= {}
# Finally, map the final sorted list to a sub-key called busyLampField
new_phone_data['busyLampFields']['busyLampField'] = sortedBlf
# That completes the payload
 
# Sends the payload into the CUCM, and either reports back or success or failure.
try:
    resp = service.updatePhone(**new_phone_data)
    print(f'SUCCESS: Device {phone_data.name} has been sorted successfully!')
except Fault:
    print('FAILED. Please check the log file and determine next steps.')
    show_history()
 
