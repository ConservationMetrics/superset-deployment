# Deploy Superset on Azure App Service

[Apache Superset](https://github.com/apache/superset/) is a data exploration and data visualization platform. The project's technical documentation makes it easy to
get up-and-running locally (i.e. on your laptop), but is too hand-wavy around
deploying to the cloud and running it in production. This `superset-deployment`
helps you deploy Superset on Azure App Service.

## Hardware & Infrastructure

Superset will run on Azure App Service. It is a multi-container deployment,
comprising

1. superset web service
2. superset celery worker
3. superset celery worker beat (job scheduler)
4. (temporarily) superset database initializer

All those run the same Docker image, which is built from the current Git repo
and uploaded to a private Container Registry.

An App Service app runs on an App Service Plan, basically representing the physical server behind the "app". Out of scope of this repo, there is also a Frizzle App Service, which we
run on the same App Service Plan as Superset; this sharing is motivated only by cost savings.

Superset has service dependencies, which we opt to host on separate servers;
this is because App Service's multi-container deployments have limited support for
data persistence and scaling out. Those dependencies are:

1. **metastore:** Azure Database for PostgreSQL flexible server
2. **cache:** Azure Cache for Redis
3. any number of **warehouse databases**
   - Warehouse databases are not handled in this repo. Rather they are added manually via the superset webapp UI after superset is running.
   - For simplicity and cost savings, we like to host the metastore and primary warehouse as separate logical databases (`CREATE DATABASE`) on the same hosted PostgreSQL instance.

### Multi-tenancy

We serve multiple clients and prefer to keep their deplpyments isolated from each other. Thus every client gets their own deployment: we create a separate Azure App Service (with its own web service, worker, initializer, etc), and PostgreSQL database for every client.

At the moment, we share one Redis cache across all clients, with its keyspace partitioned by client (**superset-deployment**'s `CACHE_KEY_PREFIX` environment variable).

## A generic, deployable Docker image

This repo roughly follows [how superset's own code base gets you started with Docker](https://github.com/apache/superset/tree/master/docker#production), but removes a lot of the distraction around local development, which was the primary focus of superset's upstream documentation.

The docker image we'll build in this repo lets you inject configuration settings
from environment variables. It does this in the script `docker/pythonpath/superset_config.py`,
which is added to the image's `PYTHONPATH`.

### Docker build

First you must commit to a specific release version of Superset, and

- update that version in [`Dockerfile`](Dockerfile)
- port any new changes to `superset_config.py` from that same tag upstream. This is manual and will require some diffing, something like:
  - cd ~/dev/superset ; git checkout 2.0.1
  - diff ~/dev/superset/docker/pythonpath_dev/superset_config.py ~/dev/superset-deployment/docker/pythonpath/superset_config.py

Now you can build the image, and might as well push it to the container registry too:

```bash
SS_VERSION=2.1.1
BUILD=$(date +"%Y%m%d-%H%M")
OUR_TAG="${SS_VERSION}_${BUILD}"
docker build -t guardiancr.azurecr.io/superset-docker:${OUR_TAG} .
docker push guardiancr.azurecr.io/superset-docker:${OUR_TAG}
```

### Running locally

Running locally is not the point here, but sometimes it's nice to sanity check something in a
more comfortable environment.

1. If hosting your own database cache locally, add those services to `docker-compose-non-dev.yml`
   - you may add local volumes here, but we won't do that in deployment.
2. Put environment variables in a new file called `docker/.env-non-dev`
   - you may first `cp docker/.env-sample docker/.env.non-dev`
   - make sure `DATABASE_URI` and `REDIS_URL` point to non-production services (assuming you want that)
3. `docker-compose -f docker-compose-non-dev.yml up`. Note that `superset-init` takes a few minutes to complete (it will terminate once done), and the rest of the app is unusable/buggy until then.
4. Open a browser to [`localhost:8080`](http://localhost:8080)

(Why do we specify `-non-dev` _everywhere?_ Just to maintain a semblance of parity with the upstream superset repo that these files are based on. Besides, the names aren't wrong.)

## Azure App Service Configuration

Your App Service service plan should have at least 8GB RAM (so they say; maybe it works with less, but I have not tested). I use Standard_P1v3.

We will run the app on its default port 8088, then use docker-compose port forwarding so that Azure App Service sees the port 80 it expects. (I am not convinced that everything is hunky-dory by merely overriding that env variable to launch the app on another port — but may be worth looking into again. for example I see places in the code or default config.py where port 8088 is hard-coded, so maybe merely port mapping in docker-compose won't always be enough? emails sent by superset and linking back to the webapp, maybe?)

You want to enable file-system logging, under **Monitoring -> App Service logs**.
The easiest way to keep your eye on logs is from the command line:

```
az webapp log tail --name my-warehouse --resource-group guardian
```

If you need those logs broken out by container, navigate to **Advanced Tools**, then **Download as zip**.

Under **Configuration** add the environment variables.

- See `docker/.env-sample` for which ones.
- Do NOT set `SUPERSET_PORT` or `WEBSITES_PORT`, since inside Docker we'll run the app on its default port.

Under **Deployment Center**, configure the app as follows:

- Use **Container Registry** and point the registry options to where your `superset-docker` image lives.
- Container type: Docker Compose (preview)
- Config: keep reading...

### Multi-container "Config"

The multi-container (docker-compose) config is a bit of a black art. It is not bona-fide docker-compose, and many features you'd expect are buggy or not implemented at all. It is valid YAML, so you can use references and such.

At the same time, the `superset-init` step seems to get messed up if you're also running the web service or celery worker at the same time as it's doing database setup. The solution here is to incrementally change which containers are running until the `init` is complete. We will do this in three steps:

#### Step 1: Maintenance page during database initialization

To avoid unwanted interactions between the app and database initialization, we start a new App by running _only_ the `superset-init` service.

However App Service will kill after a couple minutes if it hasn't found a web server listening on port 8080 so we also run a tiny unimportant web server to keep things looking "healthy" while the database initialization runs. I use `wickerlabs/maintenance`; whatever you use make sure to vet it first that it won't leak your environment variables.

The web service exposing port 8080 needs to be the _first_ service listed in a multi-container app! (This is not documented; we should report a bug to Azure...).  If instead you put `superset-init` first, App Service will kill it.

```yaml
x-superset-image: &superset-image guardiancr.azurecr.io/superset-docker:2.1.1_20230918-1726
x-superset-depends-on: &superset-depends-on []

version: "3.7"
services:
  superset:
    env_file: docker/.env-non-dev
    image: wickerlabs/maintenance:latest
    container_name: superset_app
    user: "root"
    restart: unless-stopped
    depends_on: *superset-depends-on

  superset-init:
    env_file: docker/.env-non-dev
    image: *superset-image
    container_name: superset_init
    command: ["/app/docker/docker-init.sh"]
    user: "root"
    depends_on: *superset-depends-on
```

If you don't see any logs after hitting "Save", try to load the maintenance page in a browser; I've seen App Service delay applying updates until it receives the next request (causing enormous latency on that first request!).

The database will initialize itself upon startup via the init container ([`superset-init`](./docker-init.sh)). This may take a few minutes,
even longer if your PostgreSQL instance is Burstable. Tail the logs (as shown above): If you haven't seen "Completed Step 3/3", it's not done.

#### Step 2: Remove init, Launch the App

Remove the `superset-init` service. Replace the maintenance page with the actual Superset web service. Add Celery worker and beat.

```yaml
x-superset-image: &superset-image guardiancr.azurecr.io/superset-docker:2.1.1_20230918-1726
x-superset-depends-on: &superset-depends-on []

version: "3.7"
services:
  superset:
    env_file: docker/.env-non-dev
    image: *superset-image
    container_name: superset_app
    command: ["/app/docker/docker-bootstrap.sh", "app-gunicorn"]
    user: "root"
    restart: unless-stopped
    ports:
      - "8080:8088"
    depends_on: *superset-depends-on

  superset-worker:
    env_file: docker/.env-non-dev
    image: *superset-image
    container_name: superset_worker
    command: ["/app/docker/docker-bootstrap.sh", "worker"]
    user: "root"
    restart: unless-stopped
    depends_on: *superset-depends-on

  superset-worker-beat:
    env_file: docker/.env-non-dev
    image: *superset-image
    container_name: superset_worker_beat
    command: ["/app/docker/docker-bootstrap.sh", "beat"]
    user: "root"
    restart: unless-stopped
    depends_on: *superset-depends-on
```

Notice that in the `superset` web service, we need port forwarding `ports:\n  - "80:8088"` because Superset is running on 8088 but Azure App Service requires it to be on port 8080 (or 80). Multi-container deployments seem to ignore WEBSITES_PORT, so you must do it this way.

In all these services, the `env_file` key is ignored (copy-pasta from `docker-compose-non-dev.yml`), but all the environment variables from the App Service **Configuration** are injected to the containers instead.

## Superset setup

Once you have a working website, and logging in as admin is not giving role/permission errors or toasts, you can configure the rest in the webapp:

- [ ] change password for admin user (can also delete `ADMIN_*` env vars from Configuration; they were only used for superset-init).
- [ ] add user accounts for everybody; you don't want to be logging in as `admin` anymore.
  - [See provided roles here (Alpha, Gamma, etc...)](https://apache-superset.readthedocs.io/en/0.28.1/security.html#provided-roles)
- [ ] add the warehouse database
- [ ] create your first chart or dashboard
- [ ] (optional, TBD) DNS mapping...
