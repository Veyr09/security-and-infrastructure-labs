# A small, ordinary stack. Nothing here is wrong; it is what gets built when each
# piece is added on its own and nobody adds up the monthly total afterwards.

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

resource "aws_eip" "nat" {
  for_each = aws_subnet.public
  domain   = "vpc"
}

# One NAT gateway per availability zone. Correct for availability, and the single
# largest line on a lot of small AWS bills.
resource "aws_nat_gateway" "this" {
  for_each      = aws_subnet.public
  allocation_id = aws_eip.nat[each.key].id
  subnet_id     = each.value.id
}

# No retention_in_days, so log data is kept forever and billed forever.
resource "aws_cloudwatch_log_group" "app" {
  name = "/app/api"
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/app/worker"
  retention_in_days = 0
}

resource "aws_db_instance" "main" {
  identifier              = "app-db"
  engine                  = "postgres"
  instance_class          = "db.m5.2xlarge"
  allocated_storage       = 500
  storage_type            = "gp2"
  multi_az                = true
  backup_retention_period = 7
  skip_final_snapshot     = true
  username                = "app"
  password                = "not-a-real-password-planning-only"
}

resource "aws_lambda_function" "api" {
  function_name = "app-api"
  role          = "arn:aws:iam::123456789012:role/lambda-exec"
  handler       = "index.handler"
  runtime       = "python3.9"
  memory_size   = 3008
  timeout       = 900
  filename      = "placeholder.zip"
}

resource "aws_ebs_volume" "scratch" {
  availability_zone = "eu-central-1a"
  size              = 200
  type              = "gp2"
}
