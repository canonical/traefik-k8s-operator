.. meta::
    :description: Follow step-by-step instructions to achieve a basic deployment of the Traefik charm.

.. _tutorial_basic_deployment:

Deploy the Traefik charm
========================

As part of a Kubernetes deployment, Traefik provides reverse
proxy capabilities to ingress-requiring applications. In this tutorial,
we'll go step-by-step through the process of deploying and integrating
the Traefik charm to set up a reverse proxy for a Mattermost application.

What you'll do
--------------

#. Deploy the Traefik charm
#. Deploy the Mattermost charm with a database
#. Integrate Mattermost and Traefik
#. Inspect the routing

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

.. note::

    If you're working locally, you don't need to do this step.

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

Set up the Juju model
---------------------

To manage resources effectively and to separate this tutorial's workload from
your usual work, create a new model in the controller
using the following command:

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

Deploy the Mattermost charm
---------------------------

For this tutorial, we'll use the `Mattermost charm <https://charmhub.io/mattermost-k8s>`_
as our application. Mattermost requires a database to deploy successfully,
so let's deploy the charms for Mattermost and `PostgreSQL <https://charmhub.io/postgresql-k8s>`_
and integrate them:

.. code-block::

    juju deploy mattermost-k8s --channel latest/edge
    juju deploy postgresql-k8s --channel 14/stable --trust
    juju integrate mattermost-k8s postgresql-k8s

Integrate Mattermost and Traefik
--------------------------------

Let's now provide the communication pathway between Mattermost and Traefik
by integrating them:

.. code-block::

    juju integrate mattermost-k8s traefik-k8s


Let's check what's going on with ``juju status --relations``:

.. terminal::
    :user: ubuntu
    :host: charm-tutorial-vm

    juju status --relations

    Model             Controller     Cloud/Region  Version  SLA          Timestamp
    traefik-tutorial  concierge-k8s  k8s           3.6.25   unsupported  14:42:00Z

    App             Version  Status  Scale  Charm           Channel        Rev  Address         Exposed  Message
    mattermost-k8s           active      1  mattermost-k8s  latest/edge     47  10.152.183.204  no       
    postgresql-k8s  14.23    active      1  postgresql-k8s  14/stable      925  10.152.183.105  no       
    traefik-k8s     2.11.49  active      1  traefik-k8s     latest/stable  377  10.152.183.235  no       Serving at http://10.43.45.0

    Unit               Workload  Agent  Address     Ports  Message
    mattermost-k8s/0*  active    idle   10.1.0.64          
    postgresql-k8s/0*  active    idle   10.1.0.16          Primary
    traefik-k8s/0*     active    idle   10.1.0.243         Serving at http://10.43.45.0

    Integration provider           Requirer                       Interface          Type     Message
    mattermost-k8s:secret-storage  mattermost-k8s:secret-storage  secret-storage     peer     
    postgresql-k8s:database        mattermost-k8s:postgresql      postgresql_client  regular  
    postgresql-k8s:database-peers  postgresql-k8s:database-peers  postgresql_peers   peer     
    postgresql-k8s:restart         postgresql-k8s:restart         rolling_op         peer     
    postgresql-k8s:upgrade         postgresql-k8s:upgrade         upgrade            peer     
    traefik-k8s:ingress            mattermost-k8s:ingress         ingress            regular  
    traefik-k8s:peers              traefik-k8s:peers              traefik_peers      peer  

The key relation here is:

.. code-block::

    Integration provider           Requirer                       Interface   
    traefik-k8s:ingress            mattermost-k8s:ingress         ingress   

After we ran ``juju integrate mattermost-k8s traefik-k8s``,
Juju connected the two applications together through the ``ingress`` relation endpoint.
Mattermost can now provide Traefik with its internal IP address and port
(which is ``8080`` by default). In return,
Traefik can now act as a reverse proxy for the application, automatically
generating an external URL for Mattermost. 

.. seealso::

    `ingress relation endpoint <https://charmhub.io/integrations/ingress>`_

We'll now test whether the routing works.

Inspect the routing
-------------------

First, let's verify that the Mattermost application serves traffic. We'll need
the IP address of the Mattermost application listed in the output of ``juju status``.
In the example terminal output above, the IP address is ``10.152.183.204``.
We can also grab this information generically using ``jq``:

.. code-block:: bash

    MATTERMOST_IP=$(juju status --format json | jq -r '.applications."mattermost-k8s".address')

Test the deployment using cURL:

.. code-block:: bash

    curl $MATTERMOST_IP:8080

If the deployment is successful, the output should look similar to:

.. terminal::
    :user: ubuntu
    :host: charm-tutorial-vm

    curl $MATTERMOST_IP:8080

    <a href="/traefik-tutorial-mattermost-k8s">Found</a>.

Now we can check the external URL set up by Traefik. To determine that URL,
we need to use the charm's ``show-proxied-endpoints`` action:

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
    proxied-endpoints: '{"traefik-k8s": {"url": "http://10.43.45.0"}, "mattermost-k8s":
      {"url": "http://10.43.45.0/traefik-tutorial-mattermost-k8s"}}'

Notice that Traefik has set up the URL ``http://10.43.45.0/traefik-tutorial-mattermost-k8s``
for our Mattermost application. Once again we'll test with cURL:

.. code-block::

    curl http://10.43.45.0/traefik-tutorial-mattermost-k8s

The terminal should show ``<a href="/traefik-tutorial-mattermost-k8s">Found</a>.``,
just like it did when we directly tested the Mattermost application's IP address.

Clean up the environment
------------------------

Congratulations! You successfully deployed the Traefik charm, integrated it with a basic Mattermost
application deployment, and verified that the routing works by accessing the external URL.

You can clean up your environment by following this guide:
:ref:`Tear down your deployment <juju:tear-things-down>`

Next steps
----------

You achieved a basic deployment of the Traefik charm. If you want to go farther in your
deployment or learn more about the charm, check out these pages:

* Follow the advanced tutorial involving TLS terminiation using a local certificate authority in :ref:`tutorial_tls_termination_using_a_local_ca`.
* Set up basic access authorization by :ref:`enabling BasicAuth <how_to_enable_basicauth>`.
* Learn more about the ingress relations offered by the charm in :ref:`reference_ingress_integrations`.