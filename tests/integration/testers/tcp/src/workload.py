import socket

HOST = ''

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s: 
    s.bind((HOST, 0))

    port = s.getsockname()[1]
    print(f'opened new tcp port at {port}')
    with open('./port.txt', 'w') as f:
        f.write(port)

    s.listen()                                               
    conn, addr = s.accept()                                  
    with conn:                                               
        while True:                                          
            data = conn.recv(1024)                           
            conn.sendall(data)                               
            print(data)                                      
