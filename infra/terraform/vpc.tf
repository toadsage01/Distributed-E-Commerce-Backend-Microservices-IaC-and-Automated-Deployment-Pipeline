###############################################################################
# VPC + subnets + routing
#
# Topology:
#   - 1 VPC (10.0.0.0/16)
#   - 3 public subnets  — ALB + NAT GW (one per AZ for HA)
#   - 3 private subnets — EC2 + RDS + ElastiCache
#   - 1 IGW for public egress
#   - 1 NAT GW for private egress (in public subnet AZ-a)
#       (single NAT GW saves ~$30/mo; prod should have one per AZ)
###############################################################################

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true  # required for RDS + ElastiCache to get DNS names

  tags = {
    Name = "${var.project_name}-${var.environment}-vpc"
  }
}

# ---------- Public subnets (ALB + NAT GW) ----------
resource "aws_subnet" "public" {
  count                   = length(var.public_subnet_cidrs)
  vpc_id                  = aws_vpc.main.id
  cidr_block              = var.public_subnet_cidrs[count.index]
  availability_zone       = var.availability_zones[count.index]
  map_public_ip_on_launch = true  # NAT GW needs a public IP; ALB doesn't care

  tags = {
    Name = "${var.project_name}-${var.environment}-public-${count.index + 1}"
    # ALB controller needs this tag to discover subnets
    "kubernetes.io/role/elb" = "1"
  }
}

# ---------- Private subnets (EC2 + RDS + ElastiCache) ----------
resource "aws_subnet" "private" {
  count             = length(var.private_subnet_cidrs)
  vpc_id            = aws_vpc.main.id
  cidr_block        = var.private_subnet_cidrs[count.index]
  availability_zone = var.availability_zones[count.index]

  tags = {
    Name = "${var.project_name}-${var.environment}-private-${count.index + 1}"
  }
}

# ---------- Internet Gateway ----------
resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "${var.project_name}-${var.environment}-igw"
  }
}

# ---------- Public route table ----------
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-public-rt"
  }
}

resource "aws_route_table_association" "public" {
  count          = length(aws_subnet.public)
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# ---------- Elastic IP for NAT Gateway ----------
resource "aws_eip" "nat" {
  domain = "vpc"

  tags = {
    Name = "${var.project_name}-${var.environment}-nat-eip"
  }

  # Don't allocate EIP if env=dev and we want to save cost (single NAT GW).
  # We always need it if we have private subnets — private EC2 needs egress
  # for apt-get + docker pull.
}

# ---------- NAT Gateway (in first public subnet AZ) ----------
resource "aws_nat_gateway" "main" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public[0].id

  # NAT GW must exist before private subnets try to route through it.
  # Explicit dependency on IGW so the GW is up before NAT.
  depends_on = [aws_internet_gateway.main]

  tags = {
    Name = "${var.project_name}-${var.environment}-nat-gw"
  }
}

# ---------- Private route table (routes 0.0.0.0/0 → NAT GW) ----------
resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main.id
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-private-rt"
  }
}

resource "aws_route_table_association" "private" {
  count          = length(aws_subnet.private)
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}
