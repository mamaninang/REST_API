####################
# Course: CSE138
# Date: Spring 2020
# Author: Alan Vasilkovsky, Mariah Maninang, Bradley Gallardo, Omar Quinones
# Assignment: 3
# Description: This file holds the operations GET, PUT, and DELETE for the key-value-store-view endpoint
#              as well as the key-value-store endpoint.

#              /key-value-store-view

#              If a GET request is made, it will ping the other replicas to see which ones are currently active
#              and return the view of that given replica.
#              If a PUT request is made and the socket address doesn't already exist in the view
#              then the given replica will update it's view and then broadcast a message to update
#              all the other replicas. Otherwise if the socket-address already exists a 404 bad request will
#              be returned. 
#              If a DELETE request is made and the socket-address does exist in the replicas view then it will update
#              the given replicas view. Then it will broadcast a delete to all the other given replicas.
#              Otherwise, if the socket-address doesn't exists a 404 bad request will be returned.

#               /key-value-store

#               When a replica receives a GET request for the /key-value-store endpoint, it returns the value and
#               causal-metadata associated with that key. It returns a 404 status code if the key does not exist.

#               If a PUT request is received, the replica examines the causal metadata passed in. If the causal 
#               metadata has already been generated, an entry is either added to the key-value store or updated if
#               the key already exists. If the causal-metadata has not been generated yet, the request will be placed
#               in a queue. Once the causal-metadata needed is generated, the request will be taken off the queue
#               and processed.
#
#               If a DELETE request is received, the replica returns a success message when the key gets successfully deleted
#               or an error message if the key does not exist or is already deleted.

#               Whenever a replica receives a PUT or DELETE request from a client, that replica broadcasts the request
#               to the other running replicas. It knows which other replicas to broadcast to by retrieving
#               the current view of the active replicas from the /key-value-store-view.
#
#               Once a disconnected or removed replica connects to the subnet, it's able to retrieve the requests it missed
#               by querying other replicas for their key-value stores.
#
#
###################

from flask import Flask, request, make_response, jsonify, Response
import os
import requests
import json
app = Flask(__name__)

key_value_store = {}
myIP = os.getenv('SOCKET_ADDRESS')
vectorClock = {"10.10.0.2:8085": 0, "10.10.0.3:8085":0, "10.10.0.4:8085":0}
requestQueue = {}

viewVar = os.getenv('VIEW')
view = viewVar.split(',')

#allows a disconnected or removed replica to retrieve the requests it missed during its disconnection
def wakeup(sender):

    global key_value_store
    for ip in [i for i in view if i != myIP]:
        try:
            other_kvs = requests.get('http://%s/wake' % ip, timeout=1).json()

            #if current key_value_store is not the same as other key_value_store, do this
            if key_value_store != other_kvs:
            
                for key in other_kvs:

                    if key not in key_value_store:

                        key_value_store[key] = other_kvs[key]
                        key_value_store[key]["causal-metadata"][myIP] += 1
                        vectorClock[myIP] += 1

                    elif key in key_value_store and key_value_store[key]["causal-metadata"][myIP] < other_kvs[key]["causal-metadata"][ip]:

                        key_value_store[key] = other_kvs[key]
                        key_value_store[key]["causal-metadata"][myIP] += 1

                        vectorClock[myIP] += 1

                update_other_replica_vc(sender)

            return
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            continue

@app.route('/key-value-store-view', methods=['GET', 'PUT', 'DELETE'])
def view_operations():
    global view


    if request.method == 'GET':
        broadcast(request)

        return make_response('{"message":"View retrieved successfully","view":%s}' % json.dumps(view), 200)


    elif request.method == 'PUT':
        address_to_be_added = request.json['socket-address']

        if address_to_be_added in view:
            return {"error":"Socket address already exists in the view","message":"Error in PUT"}, 404

        else:
            
            view.append(address_to_be_added)

            if request.remote_addr not in [ip.split(':')[0] for ip in view]:
                broadcast(request)

            return {"message":"Replica added successfully to the view"}, 201

            
    elif request.method == 'DELETE':
        address_to_delete = request.json['socket-address']

        if address_to_delete not in view:
            return {"error":"Socket address does not exist in the view","message":"Error in DELETE"}, 404

        else:
            view.remove(address_to_delete)

            if request.remote_addr not in [ip.split(':')[0] for ip in view]:
                broadcast(request)

            return {"message":"Replica deleted successfully from the view"}, 200

def broadcast(request):
    global view

    broadcast_range = [ip for ip in vectorClock if ip != myIP] 
    print("broadcast range: {}".format(broadcast_range))

    for ip in broadcast_range:
        url = 'http://{}:8085{}'.format(ip, request.path)
        print(url)

    #pings all other replicas to check if any are disconnected or reconnected
    if request.method == 'GET':
        old_view = view

        for ip in broadcast_range:
            try:
                res = requests.get('http://{}/status'.format(ip), headers = request.headers, timeout=1).json()
                if res is not None and ip not in view:
                    view.append(ip)


            except requests.exceptions.Timeout:
                if ip in view:
                    view.remove(ip)
                    print(view)


        if old_view != view:
            
            #if ip is not in view and is not own ip, delete address
            addresses_to_delete = [ip for ip in broadcast_range if ip not in view]

            #broadcast range is all addresses in current view except own ip
            del_broadcast_range = [ip for ip in broadcast_range if ip in view]

            #delete inactive replicas from other replicas' views
            for replica in del_broadcast_range:
                for ip in addresses_to_delete:
                    requests.delete('http://{}/key-value-store-view'.format(replica), json={"socket-address": ip})

            #put additional active replicas to other replicas' views
            put_broadcast_range = [ip for ip in view if ip != myIP]
            for replica in put_broadcast_range:
                for ip in view:
                    res = requests.put('http://{}/key-value-store-view'.format(replica), json={"socket-address": ip})
                    return res
            


    elif request.method == 'PUT' and request.json is not None:
        for ip in broadcast_range:
            try:
                requests.put('http://{}{}'.format(ip, request.path), json=request.json, timeout=1)
            except requests.exceptions.Timeout:
                view.remove(ip)
                print(view)
                
                del_broadcast_range = [ip for ip in view if ip != myIP]
                for replica in del_broadcast_range:
                    try:
                        requests.delete('http://{}/key-value-store-view'.format(replica), json={"socket-address": ip}, timeout=1)
                    except requests.exceptions.Timeout:
                        continue
                continue
        # return

    elif request.method == 'DELETE' and request.json is not None:
        for ip in broadcast_range:
            try:
                requests.delete('http://{}{}'.format(ip, request.path), json=request.json, timeout=1)
            except requests.exceptions.Timeout:
                view.remove(ip)
                print(view)
                
                del_broadcast_range = [ip for ip in view if ip != socket_address]
                for replica in del_broadcast_range:
                    try:
                        requests.delete('http://{}/key-value-store-view'.format(replica), json={"socket-address": ip}, timeout=1)
                    except requests.exceptions.Timeout:
                        continue
                continue
        # return

@app.route('/key-value-store/<key>', methods=['GET','PUT','DELETE'])
def kvs(key):
    global view

    sender = request.remote_addr + ":8085"

    #gets current view and call wakeup() to see if the replica missed any requests
    if sender not in vectorClock:
        res = requests.get('http://{}/key-value-store-view'.format(myIP), headers = request.headers).json()
        view = res["view"]

        wakeup(sender)


    if request.method == 'GET':
    
        if key_value_store[key] is None or key not in key_value_store:
            return make_response('{"doesExist":false,"error":"Key does not exist","message":"Error in GET"}', 404)
        else:
            causal = json.dumps(key_value_store[key]["causal-metadata"])
            value = key_value_store[key]["value"]

            return make_response('{"doesExist":true,"message":"Retrieved successfully","causal-metadata":%s,"value":"%s"}' % (causal, value) , 200)


    if request.method == 'PUT':

        causal = request.json["causal-metadata"]

        keyAlreadyExists = True if key in key_value_store else False

        if causal == "":

            key_value_store[key] = request.json
            vectorClock[myIP] += 1

        else:

            if causal[myIP] > vectorClock[myIP]:
                requestQueue[key] = request.json
                requestQueue[key]["method"] = request.method
                return make_response('{"message": "Request placed in a queue", "request": %s}' % json.dumps(requestQueue[key]), 200)

            else:

                key_value_store[key] = request.json

                #takes max value of each element if sender is a replica and adds 1 to own position
                if sender not in vectorClock:
                    vectorClock[myIP] += 1
                else:
                    takeMaxElement(causal)
                    vectorClock[myIP] += 1

        key_value_store[key]["causal-metadata"] = vectorClock
        value = key_value_store[key]

        kvs_broadcast(sender, key, value, request.method)
        update_other_replica_vc(sender)
        

        #check requests on hold
        if requestQueue != {}:
            done = False
            while done is not True:
                done = checkRequestQueue()

        vectorClockJson = json.dumps(vectorClock)
        if keyAlreadyExists ==  True:
            return make_response('{"message":"Updated successfully", "causal-metadata": %s}' % vectorClockJson, 200)
        else:
            return make_response('{"message":"Added successfully", "causal-metadata": %s}' % vectorClockJson, 201)

            
    if request.method == 'DELETE':

        causal = request.json["causal-metadata"]
        sender = request.remote_addr + ":8085"
        value = request.json

        if key not in key_value_store:
            return make_response('{"doesExist":false,"error":"Key does not exist","message":"Error in DELETE"}', 404)

        elif causal[myIP] > vectorClock[myIP]:
            requestQueue[key]["value"] = None
            requestQueue[key]["causal-metadata"] = request.json["causal-metadata"]
            requestQueue[key]["method"] = request.method
            return make_response('{"message": "Request placed in a queue", "request": %s}' % json.dumps(requestQueue[key]), 200)

        elif key_value_store[key]["value"] is None:
            return make_response('{"doesExist":false,"error":"Key already deleted","message":"Error in DELETE"}', 404)

        else:
            key_value_store[key]["value"] = None

            #takes max value of each element if sender is a replica and adds 1 to own position
            if sender not in vectorClock:
                vectorClock[myIP] += 1
            else:
                takeMaxElement(causal)
                vectorClock[myIP] += 1

            key_value_store[key]["causal-metadata"] = vectorClock
            value = key_value_store[key]

            kvs_broadcast(sender, key, value, request.method)
            update_other_replica_vc(sender)


            #check requests on hold
            if requestQueue != {}:
                done = False
                while done is not True:
                    done = checkRequestQueue()

            vectorClockJson = json.dumps(vectorClock)
            return make_response('{"message":"Deleted successfully", "causal-metadata":%s}' % vectorClockJson, 200) 

    
def checkRequestQueue():

    for key in requestQueue:

        causal = requestQueue[key]["causal-metadata"]
        if causal[myIP] <= vectorClock[myIP]:

            sender = request.remote_addr + ":8085"
            
            key_value_store[key] = requestQueue[key]
            key_value_store[key]["causal-metadata"] = vectorClock

            if requestQueue[key]["method"] == 'PUT':
                method = 'PUT'

            elif requestQueue[key]["method"] == 'DELETE':
                method = 'DELETE'

            value = key_value_store[key]
            del requestQueue[key]
            kvs_broadcast(sender, key, value, method)

            return False
        
    return True
    
def takeMaxElement(causal):
    for ip in vectorClock:
        if causal[ip] > vectorClock[ip]:
            vectorClock[ip] = causal[ip]
        

def kvs_broadcast(sender, key, value, method):
    
    #if sender is not a replica, broadcast
    if sender not in vectorClock:
        for ip in view:
            if ip != myIP:

                address = "http://" + ip + "/key-value-store/" + key

                if method == 'PUT':
                    response = requests.put(address, headers=request.headers, json=value)

                elif method == 'DELETE':
                    response = requests.delete(address, headers=request.headers, json=value)

                responseJson = response.json()
                newVector = responseJson["causal-metadata"]
                takeMaxElement(newVector)


def update_other_replica_vc(sender):
    if sender not in vectorClock:
        ip_to_get_vc = [ip for ip in view if ip != myIP]

        for ip in ip_to_get_vc:
            requests.put('http://{}/send-vc'.format(ip), headers = request.headers, json = {"vector-clock": vectorClock})
    return 'OK'


@app.route('/send-vc', methods = ['PUT'])
def send_vc():
    other_vc = request.json["vector-clock"]
    takeMaxElement(other_vc)
    return 'OK'

@app.route('/status', methods = ['GET'])
def status():
    return make_response('{"status": "alive"}')

@app.route('/wake', methods=['GET'])
def wake():
    return key_value_store, 200

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8085)