# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
#
# This file is included in the final Docker image and SHOULD be overridden when
# deploying the image to prod. Settings configured here are intended for use in local
# development environments. Also note that superset_config_docker.py is imported
# as a final step as a means to override "defaults" configured here
#
import json
import logging
import os
from datetime import timedelta
from typing import Optional

from flask_appbuilder.security.manager import AUTH_OAUTH
from flask_appbuilder.security.views import AuthOAuthView
from flask_appbuilder import expose
from flask import flash, get_flashed_messages
from werkzeug.wrappers import Response as WerkzeugResponse

from superset.security import SupersetSecurityManager

from cachelib.file import FileSystemCache
from celery.schedules import crontab

logger = logging.getLogger()


def get_env_variable(var_name: str, default: Optional[str] = None) -> str:
    """Get the environment variable or raise exception."""
    try:
        return os.environ[var_name]
    except KeyError:
        if default is not None:
            return default
        else:
            error_msg = "The environment variable {} was missing, abort...".format(
                var_name
            )
            raise EnvironmentError(error_msg)


SECRET_KEY = get_env_variable("SECRET_KEY")

# The SQLAlchemy connection string.
SQLALCHEMY_DATABASE_URI = get_env_variable("DATABASE_URI")

REDIS_URL = get_env_variable("REDIS_URL")
CACHE_KEY_PREFIX = get_env_variable("CACHE_KEY_PREFIX", "superset_")
REDIS_CELERY_DB = get_env_variable("REDIS_CELERY_DB", "0")
REDIS_RESULTS_DB = get_env_variable("REDIS_RESULTS_DB", "1")

RESULTS_BACKEND = FileSystemCache("/app/superset_home/sqllab")

CACHE_CONFIG = {
    "CACHE_TYPE": "redis",
    "CACHE_DEFAULT_TIMEOUT": 300,
    "CACHE_KEY_PREFIX": CACHE_KEY_PREFIX,
    "CACHE_REDIS_URL": REDIS_URL,
}
DATA_CACHE_CONFIG = CACHE_CONFIG
FILTER_STATE_CACHE_CONFIG = CACHE_CONFIG
EXPLORE_FORM_DATA_CACHE_CONFIG = CACHE_CONFIG


class CeleryConfig(object):
    broker_url = os.path.join(REDIS_URL, REDIS_CELERY_DB) + "?ssl_cert_reqs=optional"
    imports = ("superset.sql_lab",)
    result_backend = (
        os.path.join(REDIS_URL, REDIS_RESULTS_DB) + "?ssl_cert_reqs=optional"
    )
    worker_prefetch_multiplier = 1
    task_acks_late = False
    beat_schedule = {
        "reports.scheduler": {
            "task": "reports.scheduler",
            "schedule": crontab(minute="*", hour="*"),
        },
        "reports.prune_log": {
            "task": "reports.prune_log",
            "schedule": crontab(minute=10, hour=0),
        },
    }

CELERY_CONFIG = CeleryConfig

# CSP settings as provided by the Talisman extension
# See https://superset.apache.org/docs/security/#content-security-policy-csp
TALISMAN_CONFIG = {
    "force_https": False,
    "content_security_policy": {
        "img-src": "*",
        "media-src": "*",
        "frame-ancestors": ["'self'", "https://*.guardianconnector.net"]    
    }
}

# https://github.com/apache/superset/blob/master/RESOURCES/FEATURE_FLAGS.md
FEATURE_FLAGS = { "ALERT_REPORTS": True}
ALERT_REPORTS_NOTIFICATION_DRY_RUN = True
WEBDRIVER_BASEURL = "http://superset:8088/"
# The base URL for the email report hyperlinks.
WEBDRIVER_BASEURL_USER_FRIENDLY = WEBDRIVER_BASEURL

SQLLAB_CTAS_NO_LIMIT = True

# Custom config for biocultural monitoring deployments by CMI
AUTH0_DOMAIN = get_env_variable("AUTH0_DOMAIN")

# Extend the default AuthOAuthView to override the default message when the user is not authorized
class CustomAuthOAuthView(AuthOAuthView):
    @expose("/oauth-authorized/<provider>")
    def oauth_authorized(self, provider: str) -> WerkzeugResponse:
        response = super().oauth_authorized(provider)
        
        messages = get_flashed_messages(with_categories=True)
        if ('error', 'The request to sign in was denied.') in messages:
            flash("You are not yet authorized to access this application. Please contact a GuardianConnector administrator for access.", "warning")     
        return response

# https://superset.apache.org/docs/installation/configuring-superset/#custom-oauth2-configuration
# We need to override the default security manager to use Auth0
class CustomSsoSecurityManager(SupersetSecurityManager):
    authoauthview = CustomAuthOAuthView

    def oauth_user_info(self, provider, response=None):
        logging.debug("Oauth2 provider: {0}.".format(provider))
        if provider == 'auth0':
            res = self.appbuilder.sm.oauth_remotes[provider].get(f'https://{AUTH0_DOMAIN}/userinfo')
            if res.raw.status != 200:
                logger.error('Failed to obtain user info.')
                return
            me = res.json()
            # Uncomment the following line to inspect the returned user data
            # logger.debug(" user_data: %s", me)

            # Auth0 returns a full name, but Superset expects first/last name
            # We'll split the full name into two parts, but note that this is
            # not robust since some people have multiple first or last names
            # and naming conventions across the world vary (e.g. some cultures
            # put the last name first).
            name_parts = me['name'].rsplit(maxsplit=1)
            first_name = name_parts[0]
            last_name = name_parts[1] if len(name_parts) > 1 else ''

            return {
                'username' : me['email'],
                'email' : me['email'],
                'first_name': first_name, 
                'last_name': last_name
            }

# If you want to use standard Superset authentication and authorization,
# Comment out CUSTOM_SECURITY_MANAGER and AUTH_TYPE
CUSTOM_SECURITY_MANAGER = CustomSsoSecurityManager
AUTH_TYPE = AUTH_OAUTH

AUTH_USER_REGISTRATION = True
AUTH_USER_REGISTRATION_ROLE = get_env_variable("USER_ROLE", "Gamma")

OAUTH_PROVIDERS = [{
    'name': 'auth0',
    'token_key': 'access_token',
    'icon': 'fa-google',
    'remote_app': {
        'client_id': get_env_variable("AUTH0_CLIENTID"),
        'client_secret': get_env_variable("AUTH0_CLIENT_SECRET"),
        'client_kwargs': {
            'scope': 'openid profile email',
        },
        'access_token_method':'POST',
        'access_token_params':{
            'client_id':get_env_variable("AUTH0_CLIENTID")
        },
        'jwks_uri': f'https://{AUTH0_DOMAIN}/.well-known/jwks.json',
        'access_token_headers':{
            'Authorization': 'Basic Base64EncodedClientIdAndSecret'
        },
        'api_base_url':f'https://{AUTH0_DOMAIN}/oauth/',
        'access_token_url': f'https://{AUTH0_DOMAIN}/oauth/token',
        'authorize_url': f'https://{AUTH0_DOMAIN}/authorize'

    }
}]

LANGUAGES = json.loads(get_env_variable("LANGUAGES", {}))
MAPBOX_API_KEY = get_env_variable("MAPBOX_API_KEY")

# Sanitization settings to allow iframes and style tags in markdown
HTML_SANITIZATION_SCHEMA_EXTENSIONS = {
  "attributes": {
    "*": ["style","className","src","width","height","frameborder","marginwidth","marginheight","scrolling"],
  },
  "tagNames": ["style", "iframe", "h1", "h2", "h3", "h4", "h5", "h6"],
}

#
# Optionally import superset_config_docker.py (which will have been included on
# the PYTHONPATH) in order to allow for local settings to be overridden
#
try:
    import superset_config_docker
    from superset_config_docker import *  # noqa

    logger.info(
        f"Loaded your Docker configuration at " f"[{superset_config_docker.__file__}]"
    )
except ImportError:
    logger.info("Using default Docker config...")
