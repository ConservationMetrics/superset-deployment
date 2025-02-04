This folder contains the custom Superset deployment as a [CapRover one-click app](https://caprover.com/docs/one-click-apps.html).


### Add this repo to your CapRover deployment

In order to add a third party repository:
-   Login to your CapRover dashboard
-   Go to **apps** and click on **One-Click Apps/Databases** and scrolldown to the bottom
-   Under **3rd party repositories:** copy  the URL, (for example: `https://Awes0meHub.github.io/caprover-one-click-apps`) and paste it in to the text box
-   Click the **_Connect New Repository_** button

### Install from this repo using Caprover-API

You can skip the "add this repo" step shown above yet still install
Superset from this repo, using the Python [Caprover-API](https://github.com/ak4zh/Caprover-API/):

```python

cap.deploy_one_click_app(
    "superset",
    "superset",
    app_variables=variables,
    automated=True,
    one_click_repository=XXX,
)
```

