# infra/terraform

AWS infrastructure as code: S3 bucket, least-privilege IAM and remote state
(epic E6). The same code targets the local emulator or real AWS; only the files
in `envs/` change.

| File | Purpose |
|---|---|
| `main.tf` | Encrypted private bucket, pipeline user and its policy |
| `providers.tf` | Connects to AWS, or to an emulator if `aws_endpoint_url` is set |
| `envs/moto.*` | Settings for the local emulator |
| `envs/aws.*.example` | Templates for a real AWS account |

```bash
make emulator       # fresh emulator and its admin user
make infra-apply    # state bucket, terraform init and apply, pipeline key
make infra-check    # the pipeline's key can do only what it should
make infra-cycle    # create, destroy with data inside and recreate (emulator only)
make infra-test     # check the settings for real AWS; needs no account
```
Add `ENV=aws` for a real account, with credentials in `.env.aws` and the
example files copied. Applying to AWS always asks for confirmation.

`make infra-destroy` deletes the pipeline's key and then everything Terraform
created. The bucket that holds the state is not managed by Terraform and stays,
so the state's history survives: it disappears with `make emulator-down`, and on
a real account it has to be emptied and deleted by hand if you close everything.

`tests/aws.tftest.hcl` runs against a mocked provider. It proves what the code
asks AWS for (no emulator endpoint, protected bucket, least-privilege policy),
not that AWS accepts it.
