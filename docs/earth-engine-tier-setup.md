# Earth Engine Tier Setup

This is the third and most powerful way OpenH2O can pull evapotranspiration (ET)
data for your parcels. It is meant for large districts where the simpler tiers
run out of room.

OpenH2O has three ways to get ET data, in increasing order of capacity and setup effort:

1. **Public tier** (no setup): bundled demo data and any open datasets. Good for
   evaluation, not for a real district's parcels.
2. **OpenET API-key tier** (`OPENET_MODE=api`, the default): a free API key from
   [etdata.org](https://etdata.org) pulls ET for your parcels over the internet.
   This is the right choice for most districts. Its ceiling is roughly a few
   hundred parcel-queries per month, and it has no turnkey way to batch
   thousands of parcels at once.
3. **Earth Engine tier** (`OPENET_MODE=gee`, this document): for districts with
   thousands to tens of thousands of parcels, OpenH2O reads the *same* OpenET
   data directly from Google Earth Engine, where there is no per-query cap and
   the whole district can be processed in one batched job.

The Earth Engine tier pulls the identical OpenET "Ensemble" monthly dataset the
API tier uses (`projects/openet/assets/ensemble/conus/gridmet/monthly/v2_1`, band
`et_ensemble_mad`, ET in millimeters). Same numbers, a bigger faucet. Nothing
downstream changes: the ET values flow through the same cache and the same
ledger conversion the API tier already uses.

---

## Read this first: what it will cost your agency

Google Earth Engine became a paid Google Cloud product in 2023. There is a free
"noncommercial" version, but **most government water districts and Groundwater
Sustainability Agencies (GSAs) do not qualify for it**, and it is important to
understand that before you start so you are not surprised by a bill or by a
rejected application.

### Will your agency qualify for the free (noncommercial) tier?

Almost certainly not, if you are using OpenH2O the way it is designed to be used.

Google's
[Noncommercial Earth Engine policy](https://earthengine.google.com/noncommercial/)
spells out that government agencies get Earth Engine free only in three narrow
cases:

1. The agency is in a **Least Developed Country** (as defined by the United Nations).
2. The agency is part of an **Indigenous Government** recognized by its national government.
3. The agency is using Earth Engine purely for **scholarly research** (a
   peer-reviewed paper, thesis, or published report).

The same policy then says, in plain terms, that government agencies **must buy a
commercial license** for any of the following, which is exactly what an
operational water-accounting platform does:

- repeated production of data products,
- tooling for management, policy, or web applications,
- datasets, apps, or services maintained on an ongoing basis,
- workloads whose primary goal is operational.

So a typical California GSA running OpenH2O to track groundwater year after year
falls under **commercial** Earth Engine. Plan on the commercial path below. Do
not register your agency's project as noncommercial for operational use; Google
reviews these registrations and operational government use is explicitly outside
the free policy.

(For reference, the free noncommercial tiers, per Google's
[Noncommercial Tiers guide](https://developers.google.com/earth-engine/guides/noncommercial_tiers),
are the Community tier at 150 EECU-hours/month, the Contributor tier at 1,000
EECU-hours/month, and the Partner tier at 100,000 EECU-hours/month. An "EECU-hour"
is Earth Engine's unit of compute time, roughly one hour on one of its standard
processing cores. These tiers are real, but they are for the noncommercial users
above, not for an operational GSA.)

### What commercial Earth Engine actually costs

The good news: for a water district's workload, commercial Earth Engine is
cheap, as long as you pick the right plan.

Commercial pricing on the
[Google Cloud Earth Engine pricing page](https://cloud.google.com/earth-engine/pricing)
has two parts: an optional monthly platform fee, and usage fees for the compute
you actually consume.

- **Compute (usage fee):** **$0.40 per EECU-hour** for the first 10,000 EECU-hours
  in a month, dropping to $0.28 above 10,000 and $0.16 above 500,000. A water
  district will live entirely in the first band.
- **Monthly platform fee:** this is where agencies overpay if they are not
  careful. The **Individual & SMB "Limited" plan charges no platform fee at all**:
  it is pure pay-as-you-go, you pay only for the compute you use. The "Basic"
  plans (Individual/SMB Basic and Enterprise Basic) charge **$500/month** for
  included credits and support, and Enterprise Professional charges $2,000/month.
  **A small or mid-size district does not need a Basic or Enterprise plan.**
  Choose the **Limited plan** and pay only for compute.

**Cost at district scale.** Processing roughly 50,000 parcels for a year costs
about **500 EECU-hours**. On the Limited plan that is `500 x $0.40 = about $200
per year`, around $17/month, with no base fee. A smaller district with a few
hundred parcels would consume a fraction of that, on the order of single-digit
to low-tens of dollars per year. Either way it is a small fraction of the
$35,000 to $75,000 that a comparable vendor-managed analysis typically runs.

**Honest summary for your agency:** budget for commercial Earth Engine on the
pay-as-you-go Limited plan, expect roughly a few dollars to a couple hundred
dollars per year depending on how many parcels you run, and do **not** sign up
for a $500/month plan you will not use. If your use genuinely is research for
publication, you may qualify for the free tier, but confirm that with Google
before relying on it.

---

## Setup steps

These steps stand up the Earth Engine tier for your agency. Where a step can be
done from the command line with the `gcloud` tool (Google Cloud's command-line
program), the command is given. One step (registering the project for Earth
Engine) has no command-line equivalent and must be done in the web console; it
is flagged clearly.

If you do not have `gcloud` installed, install it first from
[cloud.google.com/sdk/docs/install](https://cloud.google.com/sdk/docs/install),
then run `gcloud auth login` once to sign in.

### 1. Create a Google Cloud project (or reuse one) and enable the Earth Engine API

A "project" is Google Cloud's billing-and-resource container. Each agency needs
its own, because Earth Engine meters compute per project; you cannot share
another organization's project or its quota.

```bash
# Create a new project (pick a globally-unique id)
gcloud projects create my-gsa-openh2o --name="My GSA OpenH2O"

# Point gcloud at it
gcloud config set project my-gsa-openh2o

# Link a billing account (required for commercial use). List yours first:
gcloud billing accounts list
gcloud billing projects link my-gsa-openh2o --billing-account=XXXXXX-XXXXXX-XXXXXX

# Enable the Earth Engine API and (used by some export paths) the Drive API
gcloud services enable earthengine.googleapis.com
gcloud services enable drive.googleapis.com
```

### 2. Register the project for Earth Engine (the one web-console step)

Earth Engine requires every project to be registered before it will run, and it
asks you to choose commercial or noncommercial at registration. **There is no
`gcloud` command for this step; it must be done in the browser.**

1. Go to [code.earthengine.google.com/register](https://code.earthengine.google.com/register).
2. Select your project (`my-gsa-openh2o`).
3. Choose **commercial / paid usage** unless your agency genuinely meets one of
   the three free-government cases described above. When prompted for a plan,
   the **Individual & SMB Limited (pay-as-you-go, no platform fee)** plan is the
   right default for a water district. Re-read the cost section above before
   choosing; this choice is what determines your bill.

### 3. Create a service account and download its key

OpenH2O runs on a server with no person sitting at it, so it cannot log in
through a browser the way you do. Instead it authenticates as a "service
account," which is a non-human Google identity that carries its own credentials
in a small JSON key file.

```bash
# Create the service account
gcloud iam service-accounts create openh2o-gee \
  --project=my-gsa-openh2o \
  --display-name="OpenH2O Earth Engine"

# Grant it TWO roles. Both are required:
#   1. earthengine.viewer            — read EE data and run computations
#   2. serviceusage.serviceUsageConsumer — permission to CALL the project's
#                                           APIs (without this, auth succeeds
#                                           but every Earth Engine call is
#                                           rejected with a "does not have
#                                           permission to use project" error)
gcloud projects add-iam-policy-binding my-gsa-openh2o \
  --member="serviceAccount:openh2o-gee@my-gsa-openh2o.iam.gserviceaccount.com" \
  --role="roles/earthengine.viewer"

gcloud projects add-iam-policy-binding my-gsa-openh2o \
  --member="serviceAccount:openh2o-gee@my-gsa-openh2o.iam.gserviceaccount.com" \
  --role="roles/serviceusage.serviceUsageConsumer"

# Download the JSON key (this is the secret OpenH2O will use)
gcloud iam service-accounts keys create gee-key.json \
  --iam-account=openh2o-gee@my-gsa-openh2o.iam.gserviceaccount.com
```

If you later need Earth Engine to *write* exports (a feature of the larger,
async tier), grant `roles/earthengine.writer` in addition to the two above.

IAM changes can take a couple of minutes to take effect, so if the first auth
attempt is rejected for permissions, wait briefly and retry.

The service account's email is
`openh2o-gee@my-gsa-openh2o.iam.gserviceaccount.com`; you will need it in step 4.

### 4. Place the key on the server and switch OpenH2O to the Earth Engine tier

Copy the `gee-key.json` file you just downloaded onto the server, into the
`secrets/` folder of the OpenH2O install. OpenH2O mounts that folder into the
application read-only at `/run/secrets/gee-key.json`. **This file is a
credential. Never commit it to git;** the `secrets/` folder is already excluded
from version control.

Then set these four values in the server's `.env` file:

```bash
OPENET_MODE=gee
GEE_PROJECT=my-gsa-openh2o
GEE_SERVICE_ACCOUNT_EMAIL=openh2o-gee@my-gsa-openh2o.iam.gserviceaccount.com
GEE_SERVICE_ACCOUNT_KEY_FILE=/run/secrets/gee-key.json
```

Finally, rebuild the application container so the Earth Engine library is
installed and the new key mount takes effect:

```bash
docker compose up -d --build web
```

To confirm it works, run the proof command, which authenticates without a
browser and prints ET for a handful of real parcels:

```bash
docker compose exec web python manage.py prove_gee_auth --limit 5
```

If that prints an ET table with no authentication error, the Earth Engine tier
is live. Leaving `OPENET_MODE` at its default (`api`) keeps OpenH2O on the
simpler API-key tier; `gee` is entirely opt-in.

---

## Sources

- Earth Engine noncommercial eligibility (government cases and exclusions):
  [earthengine.google.com/noncommercial](https://earthengine.google.com/noncommercial/)
- Noncommercial tier quotas (Community / Contributor / Partner EECU-hours):
  [developers.google.com/earth-engine/guides/noncommercial_tiers](https://developers.google.com/earth-engine/guides/noncommercial_tiers)
- Commercial pricing (per-EECU-hour rates, platform fees, plan tiers):
  [cloud.google.com/earth-engine/pricing](https://cloud.google.com/earth-engine/pricing)
