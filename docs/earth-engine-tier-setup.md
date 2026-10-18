<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Earth Engine Tier Setup

OpenH2O can get satellite evapotranspiration (ET) in three ways. This guide sets up
the Earth Engine tier, which reads OpenET's data through Google Earth Engine and is
meant for an organization with thousands of parcels.

1. **Public tier** (no setup). OpenH2O shows its bundled demonstration data and any
   open datasets. The public tier is for trying OpenH2O out.
2. **OpenET API-key tier** (`OPENET_MODE=api`, the default). OpenH2O uses a free key
   from [etdata.org](https://etdata.org) to ask OpenET for ET over the internet, one
   request for each parcel. As of August 2026, the free key allowed 100 requests a
   month.
3. **Earth Engine tier** (`OPENET_MODE=gee`, this guide). OpenH2O reads the same
   OpenET data directly from Earth Engine and processes every parcel in one batched
   job. A paid Earth Engine project has no monthly request limit.

The API-key tier and the Earth Engine tier read OpenET's monthly Ensemble dataset
and return the same ET values. In Earth Engine the dataset is
`projects/openet/assets/ensemble/conus/gridmet/monthly/v2_1`, and ET is the
`et_ensemble_mad` band, in millimeters.

---

## What Earth Engine costs

Google gives Earth Engine away for research, teaching, journalism and some nonprofit work. A government agency can use it free only if it is in one of the United Nations' Least Developed Countries, is part of a recognized Indigenous government, or is using it for scholarly research. Google requires a paid license for any other government use, including testing and prototyping, and for any business, such as a farm. A water agency or district running OpenH2O therefore needs the paid version. A nonprofit ditch company or mutual water company should ask Google whether it qualifies before relying on the free version.

The paid version has two charges: a monthly plan fee and a charge for computing time. Computing time costs almost nothing. Google measures it in EECU-hours and charges $0.40 an hour. (EECU stands for Earth Engine Compute Unit.) We measured the computing time on real crop parcels: a year of monthly ET for 50,000 parcels of about 70 acres uses about 0.65 EECU-hours, which costs about 26 cents. Allow a few dollars a year for recalculating past months when new data arrives.

The plan fee is most of the bill. Google's Limited plan has no plan fee: you pay only for computing time. Google offers it to self-serve customers whose work is occasional and not business-critical, and says it is not meant for enterprise customers. The other plans start at $500 a month. A small organization that matches the Limited plan's description can choose it. A public agency should ask Google which plan applies before it registers.

To estimate your own computing time, use the measured rate. Each parcel uses
0.022 EECU-seconds a year, plus 0.00035 EECU-seconds for each acre it covers:

> **EECU-hours a year = parcels × (0.022 + 0.00035 × average acres) ÷ 3,600**

| Parcels (about 70 acres each) | EECU-hours a year | Cost a year |
|-----------:|----------------:|------------------:|
| 500        | 0.0065          | under $0.01       |
| 5,000      | 0.065           | about $0.03       |
| 50,000     | 0.65            | about $0.26       |

The measurements come from `scripts/benchmarks/gee_eecu_bench.py`. If Google changes
its price, multiply the EECU-hours by the new price.

---

## Setup steps

The setup takes five steps. Run the `gcloud` commands (Google Cloud's command-line
program) on your own computer. Registering the project for Earth Engine is done in
a web browser, and steps 4 and 5 are done on the OpenH2O server.

If `gcloud` is not installed, install it from
[cloud.google.com/sdk/docs/install](https://cloud.google.com/sdk/docs/install)
and run `gcloud auth login` once to sign in.

The commands below use the project ID `my-openh2o`. A project ID must be unique
across all of Google. Choose your own and use it in place of `my-openh2o` in
every command, in the service account's email address and in the `.env` file.

### 1. Create a Google Cloud project and turn on the Earth Engine API

Google bills Earth Engine by project. Your organization needs its own project,
linked to a billing account. An existing Google Cloud project works too.

```bash
# Create a new project (pick a globally-unique id)
gcloud projects create my-openh2o --name="My OpenH2O"

# Point gcloud at it
gcloud config set project my-openh2o

# Link a billing account (required for commercial use). List yours first:
gcloud billing accounts list
gcloud billing projects link my-openh2o --billing-account=XXXXXX-XXXXXX-XXXXXX

# Enable the Earth Engine API and (used by some export paths) the Drive API
gcloud services enable earthengine.googleapis.com
gcloud services enable drive.googleapis.com
```

### 2. Register the project for Earth Engine in the browser

Earth Engine will not run in a project until you register the project. You choose
paid or free use when you register, and there is no `gcloud` command for this step.

1. Go to [code.earthengine.google.com/register](https://code.earthengine.google.com/register).
2. Select your project.
3. Choose paid use unless your organization qualifies for free use. The section
   "What Earth Engine costs" explains who qualifies. When the registration asks
   for a plan, choose the one Google allows for your organization. The plan sets
   your monthly bill.

### 3. Create a service account and download its key

On the server, OpenH2O signs in to Google as a service account: a Google identity
for a program, with its own key file. The service
account needs two roles. The first lets it read Earth Engine data and run
computations. The second lets it use the project's services. Without the second
role, the sign-in succeeds and every Earth Engine request fails.

```bash
# Create the service account
gcloud iam service-accounts create openh2o-gee \
  --project=my-openh2o \
  --display-name="OpenH2O Earth Engine"

# Grant it TWO roles. Both are required:
#   1. earthengine.viewer            — read EE data and run computations
#   2. serviceusage.serviceUsageConsumer — permission to CALL the project's
#                                           APIs (without this, auth succeeds
#                                           but every Earth Engine call is
#                                           rejected with a "does not have
#                                           permission to use project" error)
gcloud projects add-iam-policy-binding my-openh2o \
  --member="serviceAccount:openh2o-gee@my-openh2o.iam.gserviceaccount.com" \
  --role="roles/earthengine.viewer"

gcloud projects add-iam-policy-binding my-openh2o \
  --member="serviceAccount:openh2o-gee@my-openh2o.iam.gserviceaccount.com" \
  --role="roles/serviceusage.serviceUsageConsumer"

# Download the JSON key (this is the secret OpenH2O will use)
gcloud iam service-accounts keys create gee-key.json \
  --iam-account=openh2o-gee@my-openh2o.iam.gserviceaccount.com
```

The last command saves the key as `gee-key.json` in the folder where you ran it.
Google can take a few minutes to apply new roles. If the test in step 4 fails with
a permission error, wait and run it again.

### 4. Put the key on the server and switch OpenH2O to the Earth Engine tier

Copy `gee-key.json` to the server, into the `secrets/` folder of the OpenH2O
installation (create the folder if it is not there). Inside the web container,
OpenH2O reads the file as `/run/secrets/gee-key.json`. **The key file works like a
password. Never commit it to git.** Git already ignores the `secrets/` folder.

In the `.env` file in the same installation folder, set these four values:

```bash
OPENET_MODE=gee
GEE_PROJECT=my-openh2o
GEE_SERVICE_ACCOUNT_EMAIL=openh2o-gee@my-openh2o.iam.gserviceaccount.com
GEE_SERVICE_ACCOUNT_KEY_FILE=/run/secrets/gee-key.json
```

Restart the web container to load the new values:

```bash
docker compose up -d --build web
```

Then run the test command below. It needs parcels already loaded in OpenH2O. It
signs in to Google without a browser and prints ET for five parcels:

```bash
docker compose exec web python manage.py prove_gee_auth --limit 5
```

If the command prints a table of ET and no sign-in error, the Earth Engine tier is
working. To go back to the API-key tier, set `OPENET_MODE=api` and restart the web
container.

### 5. Get ET for every parcel

The same command fetches ET on either tier. Give it the first and last day of the
period you want. With `--to-ledger`, it also turns the ET into ledger entries for
the same period:

```bash
docker compose exec web python manage.py sync_openet_parcels --start-date 2024-10-01 --end-date 2025-09-30 --to-ledger
```

---

## Sources

- Who may use Earth Engine free:
  [earthengine.google.com/noncommercial](https://earthengine.google.com/noncommercial/)
- Free-use computing limits:
  [developers.google.com/earth-engine/guides/noncommercial_tiers](https://developers.google.com/earth-engine/guides/noncommercial_tiers)
- Prices and plans:
  [cloud.google.com/earth-engine/pricing](https://cloud.google.com/earth-engine/pricing)
