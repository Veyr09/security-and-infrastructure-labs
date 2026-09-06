# The same stack after the review. Every change here is one of the options the
# report offered, chosen deliberately - not a blanket downsize.

resource "aws_vpc" "main" {
  cidr_block = "10.0.0.0/16"
  tags       = { Name = "app" }
}

resource "aws_subnet" "public" {
  for_each          = toset(["eu-central-1a", "eu-central-1b", "eu-central-1c"])
  vpc_id            = aws_vpc.main.id
  availability_zone = each.value
  cidr_block        = cidrsubnet(aws_vpc.main.cidr_block, 8, index(["eu-central-1a", "eu-central-1b", "eu-central-1c"], each.value))
}

# One NAT gateway rather than three. The trade is stated rather than hidden:
# egress now depends on eu-central-1a staying up. Worth taking for this workload,
# and the wrong call for one where an AZ outage must not stop outbound traffic.
resource "aws_eip" "nat" {
  domain = "vpc"
}

resource "aws_nat_gateway" "this" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public["eu-central-1a"].id
}

# S3 traffic now skips the NAT entirely, which removes both the per-GB charge and
# a dependency on the gateway being up.
resource "aws_vpc_endpoint" "s3" {
  vpc_id       = aws_vpc.main.id
  service_name = "com.amazonaws.eu-central-1.s3"
}

resource "aws_cloudwatch_log_group" "app" {
  name              = "/app/api"
  retention_in_days = 30
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/app/worker"
  retention_in_days = 30
}

# Class reduced after a week of measurement, storage moved to gp3. Multi-AZ kept:
# this is the production database and the doubling is what it is for.
resource "aws_db_instance" "main" {
  identifier              = "app-db"
  engine                  = "postgres"
  instance_class          = "db.m5.large"
  allocated_storage       = 200
  storage_type            = "gp3"
  multi_az                = true
  backup_retention_period = 7
  skip_final_snapshot     = true
  username                = "app"
  password                = "not-a-real-password-planning-only"
}

# Memory set from the Max Memory Used figure in the logs rather than from the
# maximum. Timeout cut to what the handler actually needs, so a hung run costs
# seconds instead of fifteen minutes.
resource "aws_lambda_function" "api" {
  function_name = "app-api"
  role          = "arn:aws:iam::123456789012:role/lambda-exec"
  handler       = "index.handler"
  runtime       = "python3.12"
  memory_size   = 512
  timeout       = 30
  filename      = "placeholder.zip"
}

resource "aws_ebs_volume" "scratch" {
  availability_zone = "eu-central-1a"
  size              = 200
  type              = "gp3"
}
