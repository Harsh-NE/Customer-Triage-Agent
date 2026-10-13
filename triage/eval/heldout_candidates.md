# Held-out candidates: label each in heldout_candidates.jsonl

## H001  (https://stackoverflow.com/questions/64904390/docker-compose-up-vs-docker-compose-up-with-environment-variables)
**`docker-compose up` vs. `docker compose up` with environment variables**

I'm trying to deploy a three-node Elasticsearch cluster to an Azure Container Instance using Docker Compose. I'm loosely following this example ( from the Elasticsearch documentation and this tutorial ( from the ACI documentation.

1. [0.738] `content/manuals/compose/how-tos/environment-variables/variable-interpolation.md` > Substitute with `--env-file`
2. [0.721] `content/manuals/compose/how-tos/environment-variables/variable-interpolation.md` > `.env` file
3. [0.719] `content/manuals/compose/how-tos/environment-variables/envvars.md` > Overview

## H002  (https://stackoverflow.com/questions/65107145/docker-php-with-xdebug-3-env-xdebug-mode-doesnt-work)
**Docker PHP with Xdebug 3 env XDEBUG_MODE doesn't work**

I’m trying to config `Xdebug 3` in PHP container, and set `XDEBUG_MODE` env variable to `off` according with documentation but `xdebug_info()` shows that `mode=develop`. How to fix? Dockerfile: docker-compose.yml: xdebug info: UPDATE: My case: I use VSCode to debug my app, so I need to turn on Xdebug module only when Xdebug listening is active. Better way to do that is using env XDEBUG_CONFIG and XDEBUG_MODE, because it not require change ini files.

1. [0.738] `content/guides/laravel.md` > Create a Dockerfile for PHP-FPM
2. [0.734] `content/guides/laravel.md` > Create a Dockerfile for Workspace
3. [0.714] `content/guides/laravel.md` > 2. How do I debug my Laravel application with Docker Compose?

## H003  (https://stackoverflow.com/questions/27673563/how-to-get-into-psql-of-a-running-postgres-container)
**How to get into psql of a running postgres container?**

I created a postgres container using the tutorial on the fig website ( I named the container db. The container is running and my app connects to it fine. I tried to run the command `fig run db psql` with the db container running and got the error: How can I get into the `psql` interface in the running db container?

1. [0.737] `content/guides/postgresql.md` > Connecting to the database
2. [0.711] `content/guides/rust.md` > Run a database in a container
3. [0.709] `content/get-started/docker-concepts/running-containers/persisting-container-data.md` > Use volumes

## H004  (https://stackoverflow.com/questions/59668881/with-docker-how-can-i-bind-mount-but-also-preserve-container-files)
**With Docker, how can I bind mount but also preserve container files?**

I want to use a Docker container to run a utility (specifically Terraform) using local files. In order to quickly iterate on the code (such as `my_stuff.tf`) I want to bind mount my working directory. However, I want to consider some things as relatively stable and static, such as plugins. Basically there are three ways I want things to be handled: - `.terraform/` is stable stuff that should exist in the container but not my host directory, but needs to be preserved even after mounting.

1. [0.731] `content/manuals/engine/storage/_index.md` > Bind mounts
2. [0.713] `content/manuals/engine/storage/bind-mounts.md` > When to use bind mounts
3. [0.713] `content/manuals/build/cache/optimize.md` > Use bind mounts

## H005  (https://stackoverflow.com/questions/73843059/need-help-setting-up-golang-dockerfile)
**Need help setting up golang dockerfile**

I'm having difficulties setting up a golang dockerfile for a personal project. project structure is: The app prints a random hash every 5 seconds and appends a timestamp to it. File contents: log.go go.mod: hash.go: I scraped together the following Dockerfile: However I keep getting this error (and similar sort of errors): I've searched the web for hours trying to fix this, I genuinely don't understand what's wrong with it.

1. [0.726] `content/guides/go-prometheus-monitoring.md` > Creating a Dockerfile
2. [0.704] `content/guides/golang.md` > Prerequisites
3. [0.692] `content/guides/go-prometheus-monitoring.md` > Summary

## H006  (https://stackoverflow.com/questions/51974044/docker-compose-env-file-set-by-command-line)
**docker-compose env file set by command line**

So i want to use a custom env file depends on a custom enviroment variable passed via command line. Let's say that i start my compose with docker-compose run command: then i want to use my custom .env in my docker-compose.yml file based on ENVIROMENT variable My dockerfile: local.env: When i run this command my custom ENVIROMENT variable seems not to be set and docker still want to use default .env file. This is my error:

1. [0.724] `content/manuals/compose/how-tos/environment-variables/variable-interpolation.md` > Substitute with `--env-file`
2. [0.719] `content/manuals/compose/how-tos/environment-variables/set-environment-variables.md` > Additional information
3. [0.704] `content/manuals/compose/how-tos/environment-variables/variable-interpolation.md` > `.env` file

## H007  (https://stackoverflow.com/questions/48930991/how-to-pass-through-environment-variables-in-docker-run-through-an-env-file)
**How to pass through environment variables in docker run through an env file?**

Given this Dockerfile: I expected to be able to pass multiple variables through an `.env` file with the `key=value` format. My `delete.sh` only looks like this: I expected to see the env variables, yet they all are empty. The `--env-file` options seems to be not working. The output of the script is: I create and run the docker container via: I tried `--env-file stage.env`, `--env-file=stage.env`, `--env-file ./stage.env`, yet I don't see anything being included nor any thrown error.

1. [0.713] `content/get-started/docker-concepts/running-containers/overriding-container-defaults.md` > Setting environment variables
2. [0.711] `content/manuals/build/bake/compose-file.md` > `.env` file
3. [0.7] `content/manuals/compose/how-tos/environment-variables/variable-interpolation.md` > Substitute with `--env-file`

## H008  (https://stackoverflow.com/questions/66283653/how-to-install-composer-dependencies-in-a-container)
**How to install composer dependencies in a container?**

What I'm trying to do I'm trying to dockerize this ( php application builded on CodeIgniter 4. This app have the following dependencies which are normally installed via composer: The project structure is organized as follows: inside the `docker-compose.yml` I have a service called `php-fpm` which copies all the app files to `/var/www/html` that is the `nginx` public directory: What I need to do is install the application dependencies using composer.

1. [0.71] `content/guides/php.md` > Create a development container
2. [0.671] `content/guides/php.md` > Create Docker assets
3. [0.662] `content/guides/laravel.md` > Create a Dockerfile for PHP-FPM (production)

## H009  (https://stackoverflow.com/questions/49803158/docker-swarm-overlay-network-not-working-between-nodes)
**Docker Swarm Overlay Network Not Working Between Nodes**

i am trying to connect my docker services together in docker swarm. the network is made of 2 raspberry pi's. i can create an overlay network called `test-overlay` and i can see that services on either raspberry pi node can connect to the network. my problem: i cannot link to services between nodes with the overlay network. given the following configuration of nodes and services, `service1` can use the address ` to connect to `service2`.

1. [0.705] `content/manuals/engine/network/drivers/overlay.md` > Use the default overlay network
2. [0.694] `content/manuals/engine/network/drivers/overlay.md` > Overview
3. [0.692] `content/manuals/engine/network/drivers/overlay.md` > Use an overlay network for standalone containers

## H010  (https://stackoverflow.com/questions/57456212/error-version-in-docker-compose-yml-is-unsupported)
**ERROR: Version in "./docker-compose.yml" is unsupported**

I am running docker-compose build in a folder with the relevant docker files and yml files. I see the following error The docker-compose.yml is as follows docker-compose version docker version I can't change the version on the docker-compose.yml file.

1. [0.702] `content/manuals/desktop/release-notes.md` > Upgrades
2. [0.694] `content/manuals/desktop/previous-versions/edge-releases-mac.md` > Upgrades
3. [0.694] `content/manuals/desktop/previous-versions/edge-releases-windows.md` > Upgrades

## H011  (https://stackoverflow.com/questions/41838448/docker-cannot-pull-an-image-that-was-pushed-to-a-private-registry)
**Docker: Cannot pull an image that was pushed to a private registry**

I do this: docker pull my-private-repo.xyz.com:443/platform/abc I get following error: My docker daemon is configured as this: Here is my docker info: Added the docker info above. Any solutions? pointers on what I could be doing wrong? docker client version is this: UPDATE: Resolved. Looks like Docker is throwing ambiguous error message when the image does not exist in the repository. When I was doing this: I was expecting to pull the image with 'latest' tag to be downloaded.

1. [0.7] `content/manuals/desktop/enterprise/hardened-desktop/registry-access-management.md` > Verify restrictions are working
2. [0.697] `content/get-started/docker-overview.md` > Docker registries
3. [0.666] `content/manuals/docker-hub/image-library/mirror.md` > Configure the cache

## H012  (https://stackoverflow.com/questions/37723401/how-do-you-run-an-openshift-docker-container-as-something-besides-root)
**How do you run an Openshift Docker container as something besides root?**

I'm currently running Openshift, but I am running into a problem when I try to build/deploy my custom Docker container. The container works properly on my local machine, but once it gets built in openshift and I try to deploy it, I get the error message. I believe the problem is because I am trying to run commands inside of the container as root.

1. [0.7] `content/guides/dhi-openshift.md` > Build OpenShift-compatible images from DHI
2. [0.684] `content/guides/dhi-openshift.md` > Option 1: Use dev variants only in build stages (recommended)
3. [0.65] `content/guides/dhi-openshift.md` > Option 3: Use `oc debug` or ephemeral containers

## H013  (https://stackoverflow.com/questions/44991743/docker-connecting-php-container-to-mysql)
**Docker Connecting PHP container to MySQL**

I have two containers, a apache-php container, and a mysql db container. I am trying to get my php script to query my sql database. I am however receiving the following errors; AND when toggling the host address, i think i am missing something fundamental to docker and this is driving my crazy. My docker compose looks like; my mysql dockerfile looks like my apache dockerfile looks like; and finally my index.php looks like For my database host i have tried "db", "localhost" and "127.0.0.1".

1. [0.697] `content/guides/databases.md` > Connect to a containerized database from another container
2. [0.677] `content/guides/databases.md` > Use Docker Compose to run a database
3. [0.671] `content/guides/databases.md` > Connect to a containerized database from your host

## H014  (https://stackoverflow.com/questions/78019428/docker-compose-optional-extra-hosts-entry-from-env-variable)
**Docker Compose optional extra_hosts entry from ENV variable**

My goal is to conditionally include an entry in `extra_hosts` in my docker compose file. `docker-compose.yml` When the ENV var `MY_OPTIONAL_HOSTNAME` is set, it works as expected, but when it's not set, I get the error below: What is a "valid empty value" to set `MY_OPTIONAL_HOSTNAME` to, or how can I ignore it when not set?

1. [0.697] `content/reference/compose-file/services.md` > `extra_hosts`
2. [0.691] `content/reference/compose-file/build.md` > `extra_hosts`
3. [0.675] `content/manuals/compose/how-tos/networking.md` > Custom DNS with `extra_hosts`

## H015  (https://stackoverflow.com/questions/49864132/adding-php-extensions-using-docker-compose)
**Adding PHP Extensions using Docker Compose**

I'm trying to setup a local development environment in docker that includes nginx and php. I started with this tutorial ( and have a functioning server. My project requires that a couple PHP extensions be installed, but I'm having difficulty figuring out how to adapt this setup to include them. The documentation for the image says to put it in a dockerfile, which I have done.

1. [0.695] `content/guides/php.md` > Add a local database and persist data
2. [0.678] `content/guides/php.md` > Create Docker assets
3. [0.663] `content/guides/laravel.md` > Create a Dockerfile for PHP-CLI (production)

## H016  (https://stackoverflow.com/questions/53422818/docker-compose-logging-is-not-working-with-syslog-option)
**docker-compose logging is not working with syslog option**

I have the following docker-compose configuration: When I deploy this to DigitalOcean under Ubuntu, I can successfully run the `docker-compose up` command like so: When that command runs I can see this output: It appears that syslog is correctly configured for the `docker-compose up` command to run, but that perhaps the syslog driver is not available? All the instructions I can find for using syslog with docker refer to `docker run` commands. But how can I get syslog working with docker-compose?

1. [0.695] `content/manuals/engine/release-notes/prior-releases.md` > Logging
2. [0.69] `content/manuals/engine/logging/drivers/syslog.md` > Usage
3. [0.69] `content/manuals/engine/logging/drivers/syslog.md` > Options

## H017  (https://stackoverflow.com/questions/55762687/slow-postgresql-startup-in-docker-container)
**Slow postgresql startup in docker container**

We built a debian docker image with postgresql to run one of our service. The database is for internal container use and does not need port mapping. I believe it is installed via `apt-get` in the Dockerbuild file. We stop and start this service often, and it is a performance issue that the database is slow to startup. Although empty, takes sightly over 20s to accept connection on the first time we start the docker image. The log is as follow : Any suggetion in fixing this startup issue ?

1. [0.693] `content/guides/postgresql.md` > Advanced Configuration and Initialization
2. [0.656] `content/guides/postgresql.md` > Immediate setup & data persistence
3. [0.646] `content/guides/testcontainers-java-service-configuration.md` > Copy files into containers

## H018  (https://stackoverflow.com/questions/43803849/my-docker-container-does-not-have-ip-address-why)
**My Docker container does not have IP address. Why?**

I started a `rethinkDB` docker container using the command Now the container started successfully. I did `docker ps` Now I want to find out the IP address of this container. So I did It's returning me nothing. I couldn't find IP address for this container. I checked if the `rethinkDB` configuration page is up or not by going to ` and I see it's up and running. Why doesn't this container have any IP address? Output of `docker inspect` is as follows

1. [0.693] `content/manuals/desktop/troubleshoot-and-support/faqs/general.md` > How do I connect from a container to a service on the host?
2. [0.673] `content/manuals/engine/network/drivers/host.md` > Overview
3. [0.643] `content/manuals/desktop/features/networking/networking-how-tos.md` > Connect a container to a service on the host

## H019  (https://stackoverflow.com/questions/46917831/how-to-load-several-environment-variables-without-cluttering-the-dockerfile)
**How to load several environment variables without cluttering the Dockerfile?**

I am working on a simple Docker image that has a large number of environment variables. Are you able to import an environment variable file like with docker-compose? I cannot find anything about this in the docker file documentation. Dockerfile I guess a good way to rephrase the question would be: how do you efficiently load multiple environment variables in a Dockerfile? If you are not able to load a file, you would not be able to commit a docker file to GitHub.

1. [0.692] `content/manuals/build/bake/compose-file.md` > `.env` file
2. [0.663] `content/manuals/compose/how-tos/environment-variables/envvars.md` > Overview
3. [0.661] `content/manuals/build/building/variables.md` > `ENV` usage example

## H020  (https://stackoverflow.com/questions/71400016/trying-to-add-support-for-docker-to-existing-nextjs-project-but-getting-stat-ap)
**Trying to add support for Docker to existing NextJS project but getting "stat app/.next/standalone: file does not exist" error**

I am following this guide to add Docker support to my existing NextJS + TypeScript project and deploy to Google Cloud Run: However, the build your container step: keeps failing because it's giving me an error that "stat app/.next/standalone: file does not exist" error. I looked into my .next folder and no standalone file is being generated which is why I'm getting that error. How do I get this .next/standalone file to get created?

1. [0.691] `content/guides/nextjs.md` > Step 1: Create a development Dockerfile
2. [0.685] `content/guides/nextjs.md` > Run the containerized application
3. [0.679] `content/guides/nextjs.md` > Build the Docker image

## H021  (https://stackoverflow.com/questions/76970348/why-is-my-env-local-not-recognized-by-docker-compose-for-the-container-name-att)
**Why is my .env.local not recognized by docker-compose for the container_name attribute?**

In my starter docker project i have a `.env` file which is strangely loaded automatically. But now I wanted to rename the `.env` to `.env.local`. I also added in my `docker-compose.yml` the attribute `env_file: .env.local`. But I am since then not able to set the variable for the `container_name` attribute (`container_name: ${APP_NAME}-wordpress`). Question 1: Is docker-compose even capable of loading a file other than .env?

1. [0.689] `content/manuals/compose/how-tos/environment-variables/envvars-precedence.md` > Understanding precedence results
2. [0.669] `content/manuals/compose/how-tos/environment-variables/variable-interpolation.md` > `.env` file
3. [0.666] `content/manuals/compose/how-tos/environment-variables/envvars-precedence.md` > Simple example

## H022  (https://stackoverflow.com/questions/52586049/docker-compose-service-xxx-depends-on-service-xxx-which-is-undefined)
**Docker-Compose: Service xxx depends on service xxx which is undefined**

I'm having this error: ERROR: Service 'db' depends on service 'apache' which is undefined. Why is it saying that apache is undefined? I check the indentation. Should be the right one.

1. [0.689] `content/reference/compose-file/services.md` > `depends_on`
2. [0.652] `content/manuals/compose/how-tos/dependent-images.md` > Use another service's image as the base image
3. [0.627] `content/reference/compose-file/services.md` > `extends`

## H023  (https://stackoverflow.com/questions/23537560/docker-build-read-only-file-system)
**Docker build: read-only file system**

I'm using a `Dockerfile` to build my image and I have a command in there that says: but it fails to build the image with the following error:

1. [0.688] `content/reference/compose-file/services.md` > `read_only`
2. [0.615] `content/manuals/engine/storage/volumes.md` > Use a read-only volume
3. [0.614] `content/reference/api/extensions-sdk/DockerDesktopClient.md` > docker

## H024  (https://stackoverflow.com/questions/69537478/docker-build-for-varying-architectures-with-same-base-image-not-working)
**Docker build for varying architectures with same base image not working**

In my system, I need to create a large number of images for different devices with different architectures. For this, I have a pipeline that creates multiple images using Docker in Docker, all based on one Python:3.8 image, but for different architectures.

1. [0.687] `content/manuals/extensions/extensions-sdk/extensions/multi-arch.md` > Adding multi-arch binaries
2. [0.683] `content/guides/mistral-vibe-sandbox.md` > Step 3: Build and publish the image
3. [0.665] `content/manuals/compose/how-tos/dependent-images.md` > Overview

## H025  (https://stackoverflow.com/questions/73891299/docker-push-missing-image-name-error-when-pushing-to-gcp-artifact-registry-fro)
**Docker push "Missing image name"-error when pushing to GCP Artifact Registry from Github Actions**

I am running the google-github-actions/deploy-cloudrun ( Action on Github, which fails when trying to push a docker image to Artifact Registry. - I authenticate through an identity pool - The docker image builds successfully - However, pushing the image to `Google Artifact Registry` fails with `name invalid: Missing image name.

1. [0.685] `content/manuals/build/ci/github-actions/push-multi-registries.md` > Overview
2. [0.682] `content/manuals/build/cache/backends/gha.md` > Avoid GitHub Actions cache API throttling
3. [0.681] `content/guides/gha.md` > Build and push the image

## H026  (https://stackoverflow.com/questions/41539857/how-to-restart-container-using-container-id)
**How to restart container using container-id?**

I created a container using the command Now I see the container has exited Question: How can I restart and get in to the interactive mode for this container using its container-id? I cannot use `docker run -it <image_name>` since this expects image name and not container id. I tried using docker attach , but I think this only works for running containers. I don't want to commit this container just yet so, how can I restart and get in to interactive mode for this container using it's container-id?

1. [0.684] `content/get-started/docker-concepts/the-basics/what-is-a-container.md` > Stop your container
2. [0.68] `content/manuals/engine/containers/start-containers-automatically.md` > Use a restart policy
3. [0.652] `content/guides/rust.md` > Stop, start, and name containers

## H027  (https://stackoverflow.com/questions/65213831/failed-to-start-daemon-error-initializing-network-controller-error-creating-de)
**failed to start daemon: Error initializing network controller: Error creating default "bridge" network**

I'm using `Fedora release 33 (Thirty Three)` Docker version is `Docker version 20.10.0, build 7287ab3` First I ran `docker system prune` and since then docker daemon failed to start. I ran `systemctl start docker` command and got and then `systemctl status docker.service` I got Then `sudo dockerd --debug` and got Related to this Github issue (

1. [0.684] `content/manuals/engine/release-notes/prior-releases.md` > 1.12.5 (2016-12-15)
2. [0.682] `content/manuals/engine/release-notes/prior-releases.md` > 1.12.6 (2017-01-10)
3. [0.643] `content/manuals/engine/network/drivers/bridge.md` > Configure the default bridge network

## H028  (https://stackoverflow.com/questions/52664673/how-to-get-port-of-docker-compose-from-env-file)
**How to get port of docker-compose from env_file?**

I want to use port number defined in env file, is it possible? The below is the content of my docker-compose.yml: And this is the content of env_file.env But some errors raised: If it's possible, how should I do it? Thanks @user, thanks for your previous response. But I have another problem that the port can't be accessed in my flask app. The codes are listed as below Because the flask app need to run with the same port as the container.

1. [0.683] `content/manuals/compose/how-tos/environment-variables/variable-interpolation.md` > `.env` file
2. [0.658] `content/manuals/compose/how-tos/environment-variables/variable-interpolation.md` > local `.env` file versus <project directory> `.env` file
3. [0.656] `content/manuals/compose/how-tos/environment-variables/variable-interpolation.md` > Substitute with `--env-file`

## H029  (https://stackoverflow.com/questions/36051426/why-do-some-docker-images-require-a-command-when-run)
**Why do some docker images require a command when run?**

I find when using `docker run` I sometimes don't need to add a "command", while sometimes a "command" is a must. E.g. when running the `ubuntu` image a command isn't required: While when running `mstormo/suse`: So is this related to the specified image?

1. [0.682] `content/reference/compose-file/services.md` > `command`
2. [0.67] `content/manuals/build/concepts/dockerfile.md` > Dockerfile
3. [0.665] `content/manuals/build/building/best-practices.md` > CMD

## H030  (https://stackoverflow.com/questions/64067066/unable-to-access-ports-from-services-across-nodes-in-overlay-network-in-swarm-mo)
**Unable to access ports from services across nodes in overlay network in swarm mode**

I use the following compose file for stack deployment For the sake of convenience, I'll use `test_serv1` running via `container` in `host1` and `test_serv2` running via `container2` in `host2` for the rest of this port since actual host and container names keep changing for me.

1. [0.682] `content/manuals/engine/swarm/services.md` > Connect the service to an overlay network
2. [0.666] `content/manuals/engine/swarm/ingress.md` > Overview
3. [0.661] `content/manuals/engine/network/drivers/overlay.md` > Requirements

## H031  (https://stackoverflow.com/questions/60975243/not-able-to-start-django-project-in-local-as-well-as-in-docker)
**Not able to start `django` project in local as well as in docker**

I am using `Docker` to deploy `Python2.7` application with `Django1.8`. I am facing some issue from last two days and I found error as below. Docker Image: `python:2.7-slim-buster` Error: `uwsgi` configuration: I have installed below dependencies:

1. [0.681] `content/guides/django.md` > Create the Django project
2. [0.649] `content/guides/django.md` > Overview
3. [0.641] `content/guides/django.md` > Summary

## H032  (https://stackoverflow.com/questions/66211996/how-to-correctly-pass-ssh-key-file-from-jenkins-credentials-variable-into-to-doc)
**How to correctly pass ssh key file from Jenkins credentials variable into to docker build command?**

This question is a follow up to this question How to pass jenkins credentials into docker build command?

1. [0.68] `content/manuals/build/building/secrets.md` > SSH mounts
2. [0.679] `content/manuals/scout/integrations/ci/jenkins.md` > Overview
3. [0.676] `content/manuals/build/building/secrets.md` > Using build secrets

## H033  (https://stackoverflow.com/questions/29199884/running-docker-without-sudo-on-ubuntu-14-04)
**Running docker without sudo on Ubuntu 14.04**

I attempted to set up Docker so that I do not have to type `sudo` before using it. The steps that I took: - I started with creating a docker group with `sudo groupadd docker`; - I added my current user to the "docker" group with `sudo gpasswd -a ${USER} docker`; - I restarted docker with `sudo service docker restart`; - I closed and opened the terminal to start a new session.

1. [0.679] `content/manuals/engine/security/rootless/_index.md` > Overview
2. [0.656] `content/manuals/engine/security/rootless/_index.md` > Install
3. [0.643] `content/manuals/build/building/best-practices.md` > USER

## H034  (https://stackoverflow.com/questions/66439961/docker-build-missing-intermediate-layers-in-console-output)
**Docker Build missing intermediate layers in console output**

don't know weather it is an issue with Docker / Shell / BigSur Update, but a normal Docker Build Command like: recently started to change the default output and is now missing the intermediate layers: ( VS. the old output which included the ID's of the intermediate layers: ( How can we trigger the output of this information, as the official doc's don't say anything about it. `Docker version 20.10.2` Thanks and best regards

1. [0.679] `content/get-started/docker-concepts/building-images/using-the-build-cache.md` > Build the application
2. [0.679] `content/get-started/docker-concepts/building-images/build-tag-and-publish-an-image.md` > Building images
3. [0.672] `content/manuals/build/building/multi-stage.md` > Differences between legacy builder and BuildKit

## H035  (https://stackoverflow.com/questions/78466171/how-to-run-puppeteer-and-node-js-inside-a-docker-container)
**How to run Puppeteer and Node.js inside a Docker Container?**

I have build a scraper using Puppeteer and Node.js and now i want to dockerize it. I've tried multiple ways to tackle this, but encountering issue when puppeteer tries to start the browser for scraping. My current basic Dockerfile without Puppeteer or any other dependencies: I've tried multiple ways to update this Dockerfile in every sense (adding chrome, puppeteer) but doesn't work Code : Snippet which triggers/launches the browser Can someone help me here how can i tackle this to work ideally ?

1. [0.678] `content/guides/nodejs.md` > What will you learn?
2. [0.64] `content/guides/nextjs.md` > What will you learn?
3. [0.632] `content/guides/nodejs.md` > Run the application

## H036  (https://stackoverflow.com/questions/78981276/how-to-create-azure-devops-service-connection-docker-registry-type-other)
**How to create Azure Devops Service Connection Docker Registry Type Other**

I need help to create correctly an Azure Devops Service Connection for an Azure Container Registry (ACR) but I have only username and password to login. I have created the credential with this script: So I eneded up to create the service connection like the image below. I'm pretty sure my credential are valid but when I tried to run the Docker@2 ( task I have always the same error: ( The pipeline template that uses `Docker@2` task is defined.

1. [0.677] `content/guides/azure-pipelines.md` > Step 1: Configure a Docker Hub service connection
2. [0.654] `content/guides/azure-pipelines.md` > Step 4: Job configuration
3. [0.646] `content/guides/azure-pipelines.md` > Prerequisites

## H037  (https://stackoverflow.com/questions/55323146/docker-compose-file-has-yaml-scanner-scannererror-mapping-values-are-not-allow)
**Docker-Compose file has yaml.scanner.ScannerError : mapping values are not allowed here**

My objective is to use 1 bridge network in docker for all my docker-compose on the same host, for all my domains. I have configured 3 yml file for my docker-compose infrastructure and I'm using 1 external bridge network dockerprometheus_back-tier for all of them. One YAML file for reverse proxy (traefik) and one YAML file for each domain name (2 files).

1. [0.677] `content/manuals/compose/support-and-feedback/faq.md` > Can I use JSON instead of YAML for my Compose file?
2. [0.658] `content/manuals/compose/how-tos/environment-variables/variable-interpolation.md` > `.env` file
3. [0.637] `content/reference/compose-file/build.md` > `dockerfile_inline`

## H038  (https://stackoverflow.com/questions/27853571/why-is-docker-image-eating-up-my-disk-space-that-is-not-used-by-docker)
**Why is docker image eating up my disk space that is not used by docker**

I have setup docker and I have used completely different block device to store docker's system data: Note that `/disk/1` is using a completely different hard drive `/dev/xvdi` The problem is that when I continue download docker images and run docker containers, it seems that the other hard drive `/dev/xvda1` is also used up. I can verify this problem by remove some docker images. After I removed some docker images, `/dev/xvda1` has some more extra space now. Am I missing something?

1. [0.676] `content/manuals/engine/manage-resources/pruning.md` > Overview
2. [0.663] `content/manuals/desktop/troubleshoot-and-support/faqs/linuxfaqs.md` > Where does Docker Desktop store Linux containers?
3. [0.661] `content/manuals/desktop/troubleshoot-and-support/faqs/macfaqs.md` > Where does Docker Desktop store Linux containers and images?

## H039  (https://stackoverflow.com/questions/69607005/cannot-run-executables-with-alpine-and-busybox-docker-images)
**Cannot run executables with Alpine and Busybox docker images**



1. [0.675] `content/manuals/engine/storage/image-mounts.md` > Use an image mount in a container
2. [0.643] `content/manuals/dhi/migration/checklist.md` > Migration considerations
3. [0.64] `content/guides/dhi-backstage.md` > Update the Dockerfile

## H040  (https://stackoverflow.com/questions/72726192/golang-distroless-docker-exec-failed-no-such-file-or-directory-when-cgo-is-enab)
**Golang distroless Docker exec failed: No such file or directory when CGO is enabled**

I was trying to get a minimal example go app running inside a docker container. But I kept getting `exec /app: no such file or directory` when running the container. I checked and double checked all my paths in the image where I built and copied my application data, even looked inside the container with interactive shell to verify my `app` was there but nothing worked. My Dockerfile: After several hours of try and error I finally tried to add `CGO_ENABLED=0` to my go build command....

1. [0.675] `content/manuals/dhi/migration/examples/go.md` > Overview
2. [0.673] `content/guides/go-prometheus-monitoring.md` > Understanding the Dockerfile
3. [0.652] `content/guides/golang.md` > Create a Dockerfile for the application

## H041  (https://stackoverflow.com/questions/49029379/use-private-docker-registry-with-authentication-in-jenkinsfile)
**Use private docker registry with Authentication in Jenkinsfile**

How can I teach my Jenkisfile to login via basic auth in this setup? I'm using a custom docker image for my Jenkins build. As described in the documentation here ( I defined a docker agent like so: } If I use the following agent setup: The execution of the pipeline fails with the following exception: The problem is that the used registry requires a basic auth login. The registry runs behind a nginx reverse proxy using this ( configuration.

1. [0.675] `content/manuals/docker-hub/image-library/mirror.md` > Configure the cache
2. [0.657] `content/manuals/engine/swarm/services.md` > Create a service using an image on a private registry
3. [0.656] `content/manuals/build-cloud/builder-settings.md` > Authentication

## H042  (https://stackoverflow.com/questions/40619582/how-can-i-escape-a-dollar-sign-in-a-docker-compose-file)
**How can I escape a $ dollar sign in a docker compose file?**

I have a YAML scalar that is throwing the following error when I try to evaluate my `docker-compose.yml` file: ERROR: Invalid interpolation format for "environment" option in service "time_service": "${Time.now}" YAML: How can I maintain the same string output as written, but avoid having the docker-compose interpret it as faulty string interpolation?

1. [0.674] `content/manuals/engine/release-notes/prior-releases.md` > Builder
2. [0.648] `content/manuals/build/bake/variables.md` > Escape variable interpolation
3. [0.621] `content/reference/compose-file/interpolation.md` > Overview

## H043  (https://stackoverflow.com/questions/41278492/docker-compose-with-php-mysql-nginx-connection-issue)
**Docker Compose with PHP, MySQL, nginx connection issue**

I have problem to connect to MySQL container. docker-compose.yml PHP test script: This script reponse me : What's wrong with my code? because I think It's should be fine If anyone have a better solution Thank you for your help.

1. [0.674] `content/guides/databases.md` > Use Docker Compose to run a database
2. [0.637] `content/guides/laravel.md` > 1. Why should I use Docker Compose for Laravel?
3. [0.632] `content/guides/laravel.md` > Create a Dockerfile for Workspace

## H044  (https://stackoverflow.com/questions/58892477/list-all-files-in-build-context-and-or-in-workdir-when-building-container-image)
**List all files in Build Context and/or in WORKDIR when building container image**

I am trying to build a container image using Docker task on Azure Pipeline. I created a dockerfile, but it looks like a made a mistake cause I keep getting WARN saveError ENOENT: no such file or directory, open '/usr/src/app/package.json' I thought it would be good to list all files that exist in build context and/or WORKDIR so it would be easier for me to find a solution. Is there any appropriate dockerfile command, something like... dir ls

1. [0.674] `content/get-started/docker-concepts/building-images/build-tag-and-publish-an-image.md` > Building images
2. [0.651] `content/manuals/build/cache/optimize.md` > Keep the context small
3. [0.648] `content/manuals/build/concepts/context.md` > Filesystem contexts

## H045  (https://stackoverflow.com/questions/37236300/docker-how-to-add-new-python-dependencies-to-the-existing-docker-image)
**Docker - how to add new python dependencies to the existing docker image?**

I am a novice to docker. I am having difficulty using tensorflow docker in my Windows 10 OS. As I am following the Udacity's deep learning course, I've downloaded the `tensorflow` docker following the instruction ( and tried to launch the first assignment. But it failed to launch as the docker image was missing the `scikit-learn` package.

1. [0.674] `content/guides/jupyter.md` > Define your environment in a Dockerfile
2. [0.662] `content/manuals/build/concepts/dockerfile.md` > Example
3. [0.66] `content/guides/python.md` > Create the Docker assets

## H046  (https://stackoverflow.com/questions/71960783/building-quarkus-native-linux-amd64-x86-64-image-from-apple-m1-arm)
**Building quarkus native Linux/amd64 (x86_64) image from Apple M1 (Arm)**

I am trying to build Quarkus 2.8.0 for x86 platfom of native docker container from Apple M1 Macbook and deploy it in Linux amd64 Portainer. I was able to build the native image and when checking the file the output is: And then I am building docker container using `Dockerfile.native-micro` file, and push to my local registry using this command: The build process finished successfully without error or warning, and when I check in the local registry the container is created.

1. [0.628] `content/manuals/build/builders/drivers/kubernetes.md` > QEMU
2. [0.618] `content/manuals/build/builders/drivers/docker-container.md` > QEMU
3. [0.593] `content/manuals/build/building/multi-platform.md` > Simple multi-platform build using emulation

## H047  (https://stackoverflow.com/questions/62945254/docker-fails-with-failed-to-start-containerd-timeout-waiting-for-containerd-to)
**Docker fails with "failed to start containerd: timeout waiting for containerd to start"**

I have docker installed on Ubuntu 18.04.2 with snap. When I try to start docker it fails with the following error log. It goes over and over into a restart loop. What should I do to get docker working again?

1. [0.648] `content/manuals/desktop/previous-versions/edge-releases-windows.md` > Bug fixes and minor changes
2. [0.641] `content/manuals/engine/release-notes/26.1.md` > Bug fixes and enhancements
3. [0.633] `content/manuals/docker-hub/troubleshoot.md` > 500 response code

## H048  (https://stackoverflow.com/questions/60970697/docker-install-failing-in-linux-with-error-errno-14-https-error-404-not-foun)
**Docker install failing in linux with error [Errno 14] HTTPS Error 404 - Not Found**

I am trying to install docker in linux [Redhat] box . But its failing with below error . I have gone through the multiple articles and tried different options but it didn't resolved the issue. Few of the articles and thing that i have tried are as

1. [0.618] `content/reference/api/engine/sdk/_index.md` > Python SDK
2. [0.611] `content/manuals/desktop/release-notes.md` > Known Issues
3. [0.607] `content/manuals/engine/release-notes/prior-releases.md` > Remote API (v1.24) & Client

## H049  (https://stackoverflow.com/questions/59224272/connect-cannot-assign-requested-address)
**connect: cannot assign requested address**

I have the following error message from a Go app in Docker: which appear in the environment of the next `Dockerfile` and `docker-compose.yml` file: the `docker-compose.yml` file: here the `main.go` file: May this be helpful? in console logs I found the next lines, which I think related to the problem: the address of the database is `:: with port 5432` and while the program try to connect to `::1 with port 5432`, could this be the cause of the problem?

1. [0.571] `content/manuals/engine/release-notes/29.md` > API
2. [0.555] `content/manuals/security/authentication/single-sign-on/troubleshoot-sso.md` > User is not assigned to the organization
3. [0.546] `content/manuals/engine/release-notes/28.md` > API

## H050  (https://stackoverflow.com/questions/29238608/docker-compose-circular-container-linking)
**Docker Compose circular container linking**

I'm in the process of attempting to containerize our development environment with docker. This includes a mix of Google Appengine projects as well as services that are being eventually hosted in Google Compute engine within a containerized vm. Our current development environment bootstrapping scripts bring up elasticsearch and nginx within boot2docker and the other applications run on localhost:{product port} within the dev_appserver appengine sandbox.

1. [0.664] `content/guides/dex.md` > Using Dex with Docker
2. [0.657] `content/guides/docker-compose.md` > Why Docker Compose?
3. [0.646] `content/guides/opentelemetry.md` > Prerequisites

## H051  (https://stackoverflow.com/questions/37099008/docker-compose-build-error-when-using-parent-dir-dockerfile-for-build)
**docker-compose build error when using parent dir & dockerfile for build**

I have the following structure: In my `tests/docker-compose.yml` I have the following service defined: When do a `docker-compose build` I get:

1. [0.662] `content/reference/compose-file/build.md` > Overview
2. [0.661] `content/reference/compose-file/build.md` > Illustrative example
3. [0.649] `content/reference/compose-file/build.md` > `dockerfile`

## H052  (https://stackoverflow.com/questions/53126015/python-install-without-pip-on-ubuntu)
**python install without pip on ubuntu**

I need to install a Python package in a custom Docker container that I'm building from the official 'ubuntu' Docker image, so I want to minimize how much space this uses. Python3 installs fine and runs, but for some reason, pip is not included. So I installed via `apt install python3-pip`, this works but it is a whopping 300 megs and takes a couple of minutes to install (apparently because it installs a sh*load of stuff to build binary packages from gcc etc).

1. [0.601] `content/manuals/build/concepts/dockerfile.md` > Example
2. [0.596] `content/manuals/ai/sandboxes/install.md` > Install SBX only
3. [0.593] `content/reference/api/engine/sdk/_index.md` > Python SDK

## H053  (https://stackoverflow.com/questions/61098378/how-to-retrieve-password-from-docker-credstore)
**How to retrieve password from docker credStore?**

I'm using `docker-credential-desktop` to store my passwords for my remote docker registry. From what I understand this command should retrieve my password and username for the registry But when I run it i get this error I couldn't find the right format for the command in the docker docs. Is this the right format or am i missing something?

1. [0.659] `content/manuals/accounts/individual/manage-account.md` > Change your password
2. [0.65] `content/manuals/ai/sandboxes-api/cookbook/connect-to-cloud-with-a-bearer-token.md` > Supply a token provider {#5-supply-a-token-provider}
3. [0.641] `content/manuals/engine/release-notes/18.04.md` > Logging

## H054  (https://stackoverflow.com/questions/58666711/traefik-v2-404-while-routing-http-traffic-globally-to-https)
**Traefik v2: 404 while routing HTTP traffic globally to HTTPS**

I have the problem that I can route HTTPS traffic but I can not globally redirect the HTTP traffic to HTTPS. In my case I only want HTTPS traffic, so that I want to redirect all the incoming traffic. Currently I get an 404 error while I try to serve my URLs over HTTP. I already enabled DEBUG logs in Treafik, but I can not see any problems or unnormal stuff in the logs.

1. [0.622] `content/guides/traefik.md` > Introduction
2. [0.614] `content/guides/traefik.md` > Sending traffic to non-containerized workloads
3. [0.597] `content/guides/traefik.md` > Using Traefik in development

## H055  (https://stackoverflow.com/questions/62161864/redisinsight-docker-displaying-site-cannot-be-reached-in-browser)
**RedisInsight Docker displaying: site cannot be reached in browser**

I'm new to Redis/RedisInsight and Docker. I have windows 8. I'm trying to use RedisInsight via docker. I'm running following command. as mentioned in this tutorial. I assume I'm getting the correct console output displayed in the docker terminal. ( but when I hit the mentioned URL in browser, I'm getting ( I'm surely missing some step, can someone kindly guide me how to resolve this issue.

1. [0.593] `content/get-started/docker-concepts/running-containers/sharing-local-files.md` > Run a container
2. [0.592] `content/manuals/desktop/previous-versions/2.x-windows.md` > Bug fixes and minor changes
3. [0.589] `content/manuals/docker-hub/troubleshoot.md` > 500 response code

## H056  (https://stackoverflow.com/questions/21037983/not-able-to-connect-with-host-interface-service-inside-docker-container)
**Not able to connect with host interface service inside docker container**

I am a newbie of docker and running docker inside vagrant host. I am running redis service on host interface which is working an I am able to connect with it on host interface like localhost:6379. But I am not able to connect with it inside a docker container. I am running docker container as I am able to ping host interface inside the docker container on docker0 IP 172.17.42.1 and lx*** ip 10.0.3.1. I am getting Connection refused [tcp://172.17.42.1:6379] error.

1. [0.663] `content/manuals/desktop/features/networking/networking-how-tos.md` > Connect a container to a service on the host
2. [0.653] `content/manuals/desktop/troubleshoot-and-support/faqs/general.md` > How do I connect from a container to a service on the host?
3. [0.635] `content/manuals/ai/sandboxes/workflows/development.md` > Accessing host services from a sandbox

## H057  (https://stackoverflow.com/questions/36823982/aws-beanstalk-environment-isnt-rotating-docker-container-logs)
**AWS beanstalk environment isn't rotating docker container logs**

I am running a scala app on elastic beanstalk and the server gets overfilled with container logs which are not rotated. The default scheme of beanstalk rotates docker logs in the `/var/log/eb-docker/containers/eb-current-app/*` folder, but additional logs are accumulating in `/var/lib/docker/containers/<container-id>/*` and since they are not rotating the disk becomes full very quickly.

1. [0.604] `content/manuals/engine/logging/drivers/awslogs.md` > awslogs-region
2. [0.599] `content/manuals/engine/logging/drivers/awslogs.md` > awslogs-group
3. [0.592] `content/manuals/engine/logging/drivers/awslogs.md` > Credentials

## H058  (https://stackoverflow.com/questions/71163315/docker-eacces-permission-denied-mkdir)
**Docker EACCES permission denied mkdir**

My friend gave me a project with a dockerfile which seems to work just fine for him but I get a permission error. `error An unexpected error occurred: "EACCES: permission denied, mkdir '/usr/src/node-app/node_modules/<project_name>/api/node_modules'".` Could it be a docker version error? (

1. [0.64] `content/manuals/compose/install/uninstall.md` > Remove for all users
2. [0.62] `content/manuals/desktop/troubleshoot-and-support/troubleshoot/topics.md` > Docker commands failing in Git Bash
3. [0.619] `content/manuals/desktop/troubleshoot-and-support/troubleshoot/topics.md` > `Docker Desktop Access Denied` error message when starting Docker Desktop

## H059  (https://stackoverflow.com/questions/79847871/testcontainer-error-could-not-find-a-valid-docker-environment)
**Testcontainer error: Could not find a valid Docker environment**

Why am I suddenly encountering this error when running the repository tests locally? I am using in build.sbt: My trait definition: This setup was working earlier, but it has stopped working unexpectedly. I have already tried reinstalling Docker Desktop, but the issue persists. Notably, the problem occurs only on my local machine; the same tests run successfully in GitHub Actions.

1. [0.666] `content/manuals/testcontainers.md` > Quickstart
2. [0.648] `content/guides/testcontainers-python-getting-started.md` > Prerequisites
3. [0.639] `content/guides/testcontainers-dotnet-getting-started.md` > Prerequisites

## H060  (https://stackoverflow.com/questions/54845095/cannot-run-sysctl-command-in-dockerfile)
**Cannot run sysctl command in Dockerfile**

I'm trying to make my first dockerfile(I'm new to this), and I need the system to run the command `sysctl -w kernel.randomize_va_space=0` (its an lab env.), but I get the error: sysctl: setting key "kernel.randomize_va_space": Read-only file system Whenever I try to build the dockerfile, any suggestion how to get this around ?

1. [0.661] `content/reference/compose-file/services.md` > `sysctls`
2. [0.645] `content/manuals/engine/release-notes/27.md` > 27.0.1
3. [0.634] `content/manuals/engine/release-notes/28.md` > API

## H061  (https://stackoverflow.com/questions/75420461/gitlab-ci-cd-error-failed-to-pull-image-python-3-9-with-specified-policies-if)
**Gitlab CI/CD Error failed to pull image "python 3.9" with specified policies [if-not-present]**

I am new in devops and trying to pytest with Gitlab CI/CD and local docker runner. My job failed with this error: How can i fix it? My .gitlab-ci.yml My local runner.yml config.toml If I delete the pull_policy field in config.toml or replace the value with 'always' - the error does not go away.

1. [0.613] `content/manuals/scout/integrations/ci/gitlab.md` > Overview
2. [0.582] `content/manuals/engine/release-notes/20.10.md` > Packaging
3. [0.577] `content/manuals/build/policies/usage.md` > Testing in CI/CD

## H062  (https://stackoverflow.com/questions/55275790/ebusy-resource-busy-or-locked-in-docker-when-trying-to-do-npm-install)
**EBUSY: resource busy or locked in Docker when trying to do npm install**

I keep getting this error when I am trying to install an npm package. Volumes in docker-compose.yml is set as follows: I want to run installs from inside the container it keeps giving me the following:

1. [0.614] `content/guides/nextjs.md` > Build the Docker image
2. [0.607] `content/manuals/engine/release-notes/17.09.md` > Runtime
3. [0.589] `content/manuals/engine/release-notes/20.10.md` > Contrib

## H063  (https://stackoverflow.com/questions/34902986/kubernetes-docker-pod-starting-fails-except-one)
**Kubernetes: Docker pod starting fails except one**

We are running a Jetty service on the Google container engine. This one service runs just fine in a pod with a rc. We can shut it down, rebuild it and do all manner of things to it and it will still work. Now we want to extend our infrastructure with a debian image that runs something else. Locally, the docker works fine and we can access the debian commandline. Once we try to run the pod in the cloud, we get issues.

1. [0.662] `content/manuals/desktop/use-desktop/kubernetes.md` > Troubleshooting
2. [0.609] `content/manuals/desktop/previous-versions/2.x-mac.md` > Bug fixes and minor changes
3. [0.603] `content/manuals/desktop/previous-versions/2.x-windows.md` > Known issues

## H064  (https://stackoverflow.com/questions/47977699/add-failed-no-such-file-directory-while-building-docker-image)
**ADD failed : No such file/Directory while building docker image**

I have below Dockerfile: My directory structure is: when I am building the docker image using below command: It shows below error: Why it shows this error when I have the directory and my file is also present.

1. [0.635] `content/manuals/build/concepts/dockerfile.md` > Building
2. [0.63] `content/manuals/build/policies/inputs.md` > Example Dockerfile
3. [0.629] `content/manuals/dhi/how-to/customize.md` > Customize a Docker Hardened Image

## H065  (https://stackoverflow.com/questions/51190889/setting-up-docker-permission-to-vsts-agent-in-a-private-pipeline)
**setting up docker permission to VSTS agent in a private pipeline**

I have set a private pipeline with linux vm and agent is install and in the portal it shows that the agent is active. I also have install docker. In the same machine if I use sudo docker it works. So I am sure it is a permission issues when the VSTS agent is running the command. Not sure what which user i need to give which premission so that docker command will run when I initial a build from VSTS.

1. [0.66] `content/manuals/ai/sandboxes/security/_index.md` > What the agent can do inside the sandbox
2. [0.614] `content/manuals/ai/sandboxes/security/isolation.md` > Docker Engine isolation
3. [0.611] `content/manuals/docker-hub/repos/manage/builds/setup.md` > Service users for team autobuilds

## H066  (https://stackoverflow.com/questions/73207167/nuxt-not-found-inside-docker-image)
**nuxt: not found inside docker image**

I am building a docker environment for a nuxt 3 app. This is my `package.json` file: This is my `docker-compose.yml` file: And this is my `Dockerfile` for the nuxt 3 app: This is my `.dockerignore` file: When I run `docker compose up` I get the following error from building the docker file: Here is what I have tried so far to solve this: - Deleted all containers, volumes etc.

1. [0.6] `content/guides/vuejs.md` > Build the Docker image
2. [0.597] `content/guides/laravel.md` > Create a Dockerfile for Workspace
3. [0.589] `content/guides/dhi-backstage.md` > Update the Dockerfile

## H067  (https://stackoverflow.com/questions/63924161/postgresql-container-not-starting-chmod-changing-permissions-of-bitnami-post)
**postgresql container not starting: chmod: changing permissions of '/bitnami/postgresql/data': Operation not permitted**

bitnami/postgresql is unable to start with volume mount. I am using 10.14.0 version of the official docker image. Container starts without the volume mount: with volume mount with docker-compose file output: I am unable to find any solution to this. other containers don't seem to have this problem. Please help if anyone finds solution to this problem.

1. [0.614] `content/guides/postgresql.md` > Quick start (minimal viable container)
2. [0.607] `content/get-started/docker-concepts/running-containers/persisting-container-data.md` > Use volumes
3. [0.605] `content/guides/rust.md` > Run a database in a container

## H068  (https://stackoverflow.com/questions/45423334/stopping-docker-containers-from-being-there-on-startup)
**Stopping Docker Containers from Being there on Startup**

Whenever I start Docker on my Mac, there are four containers that come along for the ride and start up automatically. How do I tell (Docker? The containers?) that I don't need these four containers to start up automatically anymore?

1. [0.663] `content/guides/golang.md` > Better productivity with Docker Compose
2. [0.652] `content/get-started/docker-concepts/the-basics/what-is-a-container.md` > Stop your container
3. [0.649] `content/manuals/engine/containers/start-containers-automatically.md` > Restarting foreground containers

## H069  (https://stackoverflow.com/questions/54984418/alternative-to-openjdk8-alpine-for-kafka-streams)
**Alternative to openjdk:8-alpine for Kafka Streams**

I am using openjdk:8-alpine for deploying Kafka Streams application. I am using Windowing and it crashes with below error: Searching for the above issue, i came across But it didn't helped. So, Alpine uses musl-libc but it's not supported by RocksDB. The issue to add support for musl-libc to RocksDB: facebook/rocksdb#3143 ( Question:Is there any openjdk docker image using which i can make my Kafka Stream application run and which won't give rocksdb issue?

1. [0.597] `content/guides/kafka.md` > Launching Kafka
2. [0.58] `content/guides/kafka.md` > Overview
3. [0.578] `content/guides/kafka.md` > Adding cluster visualization

## H070  (https://stackoverflow.com/questions/73334144/running-django-app-with-docker-unrecognized-runserver-arguments)
**Running django app with docker, unrecognized runserver arguments**

I'm having a problem with starting my django project in docker container. I have tried this in multiple ways, for example: or just first time i have tried this i got no error, but i couldn't open the app in browser so i tried it again and then it stopped working completely. I'm getting this error: My docker-compose.yml My Dockerfile

1. [0.655] `content/guides/django.md` > Update the Dockerfile
2. [0.638] `content/guides/django.md` > Run the application
3. [0.635] `content/manuals/ai/model-runner/_index.md` > Networking
