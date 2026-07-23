.. meta::
    :description: Follow step-by-step instructions to achieve a basic deployment of the Traefik charm.

.. _tutorial_basic_deployment:

Deploy the Traefik charm
========================

As part of a Kubernetes deployment, Traefik provides reverse
proxy capabilities to ingress-requiring applications. In this tutorial,
we'll go step-by-step through the process of deploying and integrating
the Traefik charm to set up a reverse proxy for a simple Flask application.

What you'll do
--------------

#. Deploy the Traefik charm
#. Deploy a simple Flask application
#. Integrate Traefik and the Flask application
#. Verify the routing in the terminal and in a browser

What you'll need
----------------

You will need a working station, e.g., a laptop, with AMD64 architecture.
Your working station should have at least 4 CPU cores, 8 GB of RAM, and 30 GB of disk space.

.. tip::

    You can use Multipass to create an isolated environment by running:

    .. code-block::

        multipass launch 24.04 --name charm-tutorial-vm --cpus 4 --memory 8G --disk 30G

    To be able to work inside the Multipass VM, log in with the following command:

    .. code-block:: bash

        multipass shell charm-tutorial-vm 

This tutorial requires the following software to be installed on your working station
(either locally or in the Multipass VM):

* Juju 3.6+
* Canonical Kubernetes 1.32+

Use `Concierge <https://github.com/canonical/concierge>`_ to set up Juju
and Canonical Kubernetes:

.. code-block::

    sudo snap install --classic concierge
    sudo concierge prepare -p k8s

This first command installs Concierge, and the second command uses Concierge
to install and configure Juju and Canonical Kubernetes.

For this tutorial, Juju must be bootstrapped to a Canonical Kubernetes controller.
Concierge should complete this step for you, and you can verify by checking for
``msg="Bootstrapped Juju" provider=k8s``
in the terminal output and by running ``juju controllers``.

If Concierge did not perform the bootstrap, run:

.. code-block:: bash

    juju bootstrap k8s tutorial-controller

Finally, for Traefik to receive an external IP address, the Kubernetes cluster
must have a configured load balancer. Concierge should configure the load
balancer for you, and you can verify by checking for ``load-balancer: enabled``
in the output of ``sudo k8s status``.

Set up the Juju model
---------------------

To manage resources effectively and to separate this tutorial's workload from
your usual work, create a new model in the controller with:

.. code-block:: bash

    juju add-model traefik-tutorial

Deploy the Traefik charm
------------------------

Let's begin by deploying the Traefik charm:

.. code-block:: bash

    juju deploy traefik-k8s --trust 


By default the latest stable release of the charm will be deployed.
We must also use the ``--trust`` flag to provide Traefik with elevated permissions to
interact with the Kubernetes environment.

The charm may need a couple of minutes to finish deploying. Monitor the status
of the deployment with ``juju status``.
Once the deployment has finished, the output of ``juju status`` should look similar to:

.. terminal::
    :user: ubuntu
    :host: charm-tutorial-vm

    juju status

    Model             Controller     Cloud/Region  Version  SLA          Timestamp
    traefik-tutorial  concierge-k8s  k8s           3.6.25   unsupported  14:22:33Z

    App          Version  Status  Scale  Charm        Channel        Rev  Address         Exposed  Message
    traefik-k8s  2.11.49  active      1  traefik-k8s  latest/stable  377  10.152.183.235  no       Serving at http://10.43.45.0

    Unit            Workload  Agent  Address     Ports  Message
    traefik-k8s/0*  active    idle   10.1.0.243         Serving at http://10.43.45.0

Traefik is active, idle, and ready to route traffic.
Now we need to provide Traefik with an application.

Deploy the Flask application
----------------------------

For this tutorial, we'll use the `Flask K8s charm <https://charmhub.io/flask-k8s>`_
as our application. Let's deploy it now:

.. code-block::

    juju deploy flask-k8s 

Integrate Traefik and the Flask application
-------------------------------------------

We'll provide a communication pathway between the Flask application
and Traefik by integrating them:

.. code-block::

    juju integrate traefik-k8s flask-k8s


Let's check what's going on with our deployment using ``juju status --relations``:

.. terminal::
    :user: ubuntu
    :host: charm-tutorial-vm

    juju status --relations

    Model             Controller     Cloud/Region  Version  SLA          Timestamp
    traefik-tutorial  concierge-k8s  k8s           3.6.25   unsupported  16:48:25Z

    App          Version  Status  Scale  Charm        Channel        Rev  Address        Exposed  Message
    flask-k8s             active      1  flask-k8s    latest/edge     19  10.152.183.85  no       
    traefik-k8s  2.11.49  active      1  traefik-k8s  latest/stable  377  10.152.183.62  no       Serving at http://10.43.45.0

    Unit            Workload  Agent  Address     Ports  Message
    flask-k8s/0*    active    idle   10.1.0.85          
    traefik-k8s/0*  active    idle   10.1.0.166         Serving at http://10.43.45.0

    Integration provider      Requirer                  Interface       Type     Message
    flask-k8s:secret-storage  flask-k8s:secret-storage  secret-storage  peer     
    traefik-k8s:ingress       flask-k8s:ingress         ingress         regular  
    traefik-k8s:peers         traefik-k8s:peers         traefik_peers   peer  

The key relation here is the one between Traefik and the Flask application:

.. code-block::

    Integration provider      Requirer                  Interface   
    traefik-k8s:ingress       flask-k8s:ingress         ingress  

After we ran ``juju integrate traefik-k8s flask-k8s``,
Juju connected the two applications together through the ``ingress`` relation endpoint.
The Flask application can now provide Traefik with its internal IP address and port
(which is ``8000`` by default). In return,
Traefik can now act as a reverse proxy for the application, automatically
generating an external URL. 

.. seealso::

    `ingress relation endpoint <https://charmhub.io/integrations/ingress>`_

We'll now test whether the routing works.

Verify the routing
------------------

First, let's verify that the Flask application serves traffic. We'll need
the IP address of the Flask unit listed in the output of ``juju status``.
In the example terminal output above, the IP address is ``10.1.0.85``.
We can also grab this information generically using ``jq``:

.. code-block:: bash

    FLASK_IP=$(juju status --format json | jq -r '.applications."flask-k8s".units."flask-k8s/0".address')

Test the deployment using cURL:

.. code-block:: bash

    curl $FLASK_IP:8000

If the deployment is successful, the output should show HTML containing
``<title>Welcome to flask-k8s Charm</title>``.

Now we can check the external URL set up by Traefik to verify that traffic
is routed through Traefik. To determine the external URL,
let's use the charm's ``show-proxied-endpoints`` action:

.. code-block:: bash

    juju run traefik-k8s/0 show-proxied-endpoints

The action lists all the endpoints proxied by Traefik. The command should
output something similar to:

.. terminal::
    :user: ubuntu
    :host: charm-tutorial-vm

    juju run traefik-k8s/0 show-proxied-endpoints

    Running operation 1 with 1 task
      - task 2 on unit-traefik-k8s-0

    Waiting for task 2...
    proxied-endpoints: '{"traefik-k8s": {"url": "http://10.43.45.0"}, "flask-k8s": {"url":
      "http://10.43.45.0/traefik-tutorial-flask-k8s"}}'

Notice that Traefik has set up the URL ``http://10.43.45.0/traefik-tutorial-flask-k8s``
for our Flask application. Once again we'll test with cURL:

.. code-block::

    curl http://10.43.45.0/traefik-tutorial-flask-k8s

The terminal should show the same HTML output as before, thus confirming that
traffic is being routed through Traefik.

Visit in a browser
~~~~~~~~~~~~~~~~~~

The HTML output from cURL can be difficult to read in a terminal.
As a final step, let's visit the Flask application in a browser.

.. note::

    If you're using Multipass for this tutorial, you will need to route the
    IP from Multipass. First you'll need the IP of the Multipass VM.
    Outside the Multipass VM run:

    .. code-block::

        multipass info charm-tutorial-vm

    Several IPs may be listed in the output; use the first listed IP.

    We also need the IP for the Traefik application listed in the output from the
    ``show-proxied-endpoints`` action.
    In the output shown previously, this IP is ``10.43.45.0``.

    Then route:

    .. code-block::

        sudo ip route add 10.43.45.0 via <Multipass VM IP>

Access the Flask application at ``http://10.43.45.0/traefik-tutorial-flask-k8s`` in
your browser. You should see the message
"Congratulations! You've successfully deployed the flask-k8s charm."

Clean up the environment
------------------------

Congratulations! You successfully deployed the Traefik charm, integrated it with a basic Flask
application, and verified that the routing works by accessing the external URL.

You can clean up your environment by following this guide:
:ref:`Tear down your deployment <juju:tear-things-down>`

.. note::

    If you used Multipass for this tutorial, remove the route with:

    .. code-block::

        sudo ip route del 10.43.45.0

Next steps
----------

You achieved a basic deployment of the Traefik charm. If you want to go farther in your
deployment or learn more about the charm, check out these pages:

* Follow the advanced tutorial involving TLS termination using a local certificate authority in :ref:`tutorial_tls_termination_using_a_local_ca`.
* Set up basic access authorization by :ref:`enabling BasicAuth <how_to_enable_basicauth>`.
* Learn more about the ingress relations offered by the charm in :ref:`reference_ingress_integrations`.