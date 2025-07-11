# Deploy Superset using CapRover or Docker Compose

[Apache Superset](https://github.com/apache/superset/) is a data exploration and data visualization platform.

The project's technical documentation makes it easy to get up-and-running locally (i.e. on your
laptop), but does not support a dockerized production deployment. Instead they recommend using helm,
either on a Kubernetes cluster or a single VM using minikube.

This `superset-deployment` helps you deploy Superset for production using **docker compose** or [**CapRover**](https://caprover.com/).

It also takes an opinionated approach that it will be deployed with:
- Auth0 login
- Postgresql for the database
- Redis for the cache

## Hardware & Infrastructure

Superset is a multi-container deployment, comprising

1. superset web service
2. superset celery worker
3. superset celery worker beat (job scheduler)
4. (temporarily) superset database initializer

All those run the same Docker image, which is built from the current Git repo
and uploaded to a private Container Registry.

Superset has other service dependencies that you MAY host on the same VM or on separate servers.
Those dependencies are:

1. **metastore:** PostgreSQL server
2. **cache:** Redis
3. any number of **data sources** (SQL databases)
   - Data Sources are not handled in this repo. Rather they are added manually via the superset webapp UI after superset is running.
   - For simplicity and cost savings, we like to host the metastore and primary warehouse as separate logical databases (`CREATE DATABASE`) on the same hosted PostgreSQL instance.

### Multi-tenancy

We serve multiple clients and prefer to keep their deployments isolated from each other. Thus every client gets their own deployment: we create a separate VM (with its own web service, worker, initializer, etc), and PostgreSQL database for every client.

## A generic, deployable Docker image

This repo roughly follows [how superset's own code base gets you started with Docker](https://github.com/apache/superset/tree/master/docker#production), but removes a lot of the distraction around local development, which is the focus of superset's documentation.

The docker image we'll build in this repo
* lets you inject configuration settings from environment variables _without having to mount a `superset_config.py` from the host filesystem._ This is desireable when we want to reduce dependencies at deploy time. It does this by building `docker/pythonpath/superset_config.py` into the image itself, and adding it to the image's `PYTHONPATH`.
* adds OAuth authentication (more on this below), including building in the required `Authlib` python package.

### Docker build

First you must commit to a specific release version of Superset, and

- update that version in [`Dockerfile`](Dockerfile)
- port any new changes to `superset_config.py` from that same tag upstream. This is manual and will require some diffing, something like:
  - cd ~/dev/superset ; git checkout 4.1.2
  - diff ~/dev/superset/docker/pythonpath_dev/superset_config.py ~/dev/superset-deployment/docker/pythonpath/superset_config.py

Now you can build the image, and might as well push it to the container registry too:

```bash
SS_VERSION=4.1.2
BUILD=$(date +"%Y%m%d-%H%M")
OUR_TAG="${SS_VERSION}_${BUILD}"
docker build -t guardiancr.azurecr.io/superset-docker:${OUR_TAG} .
docker push guardiancr.azurecr.io/superset-docker:${OUR_TAG}
```

### Running locally

Running locally is not the point here, but sometimes it's nice to sanity check something in a
more comfortable environment.

1. If hosting your own database cache locally, add those services to `docker-compose.yml` or create a `docker-compose.override.yml`
   - you may add local volumes here, but we won't do that in deployment.
2. Put environment variables in a new file called `docker/.env`
   - you may first `cp docker/.env-sample docker/.env`
   - make sure `DATABASE_URI` and `REDIS_URL` point to non-production services (assuming you want that)
3. `docker compose up`. Note that `superset-init` takes a few minutes to complete (it will terminate once done), and the rest of the app is unusable/buggy until then.
4. Open a browser to [`localhost:8088`](http://localhost:8088)

### Running in Production

Using **CapRover**:
- install superset using the [one-click app](./caprover/one-click-apps/README.md)

Using **docker compose**
- Run `docker compose up`


#### Prerequisites

Your VM should have at least 4GB RAM (The official guidance from Apache is 8GB but I've never had a problem with only 4GB).

We will run the app on its default port `8088`: you will need to point incoming requests to that.

#### Environment variables

In all these services, the environment file specified by the `env_file` key is optional. This is to allow certain deployment scenarios where the environment variables get injected by other means besides a file.

#### Database initialization

To initialize things you need to define an "admin" user (which will likely never be used again)
by adding environment variables `ADMIN_EMAIL` and `ADMIN_PASSWORD` on the `superset-init` service.

The database will initialize itself upon startup via the init container ([`superset-init`](./docker-init.sh)). This may take a few minutes.
Tail the logs (as shown above): If you haven't seen "Completed Step 3/3", it's not done.

After it's done, you _may_ remove the `superset-init` service.


## Authentication

We are using auth0 for authentication. For auth0 to work, you will need to provide the relevant environmental variables shown in `.env`, and configure your auth0 tentant according to your needs. By default, Superset account registration is enabled. Users may authenticate using auth0 based on their username, which should match their auth0 email address. Upon initial registration, the user will first see a message that their request to sign in was denied. That is because the user's account needs to be approved by an auth0 admin; once that's been done, they will be able to log in to Superset without issue.

Superset uses [Flask-AppBuilder](https://flask-appbuilder.readthedocs.io/en/latest/security.html#authentication-methods) for authentication, which can only handle one type of authentication method and this means the standard authentication protocols are not accessible. Hence, for initial Superset db setup, we are using environmental variables to create an admin user whose username should match your auth0 email account.

## User roles

The starting Role of the user once approved is determined by a `USER_ROLE` environmental variable. Please see [this guide on Superset roles](https://superset.apache.org/docs/security/) to set the appropriate starting Role for your deployment. The fallback value is "Alpha" if the var is not set.

Currently, we default to "Alpha" because it grants broad dashboard/chart access without the ability to view or edit database credentials or create new datasets, thus striking a balance between usability and security. "Admin privileges" are reserved for a small group, such as the very first Superset user. "Gamma" can be appropriate for strictly read-only users needing per-asset permissions. 

For an exhaustive list of roles and permissions, see [STANDARD_ROLES.md](https://github.com/apache/superset/blob/master/RESOURCES/STANDARD_ROLES.md). Here's a truncated summary:

| Role   | Access Level Summary |
|--------|----------------------|
| Admin  | Full access. Can manage users, roles, all data sources, dashboards, and credentials. Can grant/revoke access. |
| Alpha  | Can access all data sources and dashboards, create/modify their own dashboards/slices. Cannot manage users or view credentials. |
| Gamma  | Read-only by default. Can only see charts/dashboards from explicitly granted data sources. Cannot edit or add data sources. |

## Optional environmental variables

To allow for flexible customization, we have provided several optional environmental variables (commented out in `.env.sample`):

* `APP_NAME`: if you want the page title for the dashboard to be something different than "Superset"
* `APP_ICON`: to change the Superset logo shown on the top left of the window.
* `FRAME_ANCESTORS`: to provide a comma separated list of permissible frame ancestors for your CSP.
* `MAPBOX_API_KEY`

## Superset setup

Once you have a working website, and logging in as admin is not giving role/permission errors or toasts, you can configure the rest in the webapp:

- [ ] change password for admin user (can also delete `ADMIN_*` env vars from Configuration; they were only used for superset-init).
- [ ] add user accounts for everybody; you don't want to be logging in as `admin` anymore.
  - [See provided roles here (Alpha, Gamma, etc...)](https://github.com/apache/superset/blob/master/docs/docs/security/security.mdx)
- [ ] add the data store
- [ ] create your first chart or dashboard
- [ ] (optional, TBD) DNS mapping...

## Upgrading

Often it's enough to bump the Docker image to a newer version. However some
superset upgrades require a Database migration. That is done by running:

    superset db upgrade

This is easy to do if you have direct access to exec into the Docker container.
However if you don't, or if you want to automate this step away, you could
add it to the `command` of one of the Docker services:

```yaml
    command: sh -c "superset db upgrade ; /app/docker/docker-boostrap beat"
```

The one-click app for CapRover already includes this in its `init-and-beat` service.
