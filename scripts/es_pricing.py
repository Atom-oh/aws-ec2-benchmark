# AWS EC2 On-Demand Pricing (Seoul, ap-northeast-2, USD/hour)
# Source: AWS Pricing Calculator (Jan 2026)

PRICING = {
    # Intel 5th Gen
    "c5.xlarge": 0.192, "c5a.xlarge": 0.172, "c5d.xlarge": 0.218,
    "c5n.xlarge": 0.242, "m5.xlarge": 0.214, "m5a.xlarge": 0.192,
    "m5ad.xlarge": 0.232, "m5d.xlarge": 0.254, "m5zn.xlarge": 0.413,
    "r5.xlarge": 0.282, "r5a.xlarge": 0.252, "r5ad.xlarge": 0.292,
    "r5b.xlarge": 0.336, "r5d.xlarge": 0.322, "r5dn.xlarge": 0.376,
    "r5n.xlarge": 0.334,
    # Intel 6th Gen
    "c6i.xlarge": 0.192, "c6id.xlarge": 0.242, "c6in.xlarge": 0.254,
    "m6i.xlarge": 0.214, "m6id.xlarge": 0.268, "m6idn.xlarge": 0.322,
    "m6in.xlarge": 0.268, "r6i.xlarge": 0.282, "r6id.xlarge": 0.336,
    # Intel 7th Gen
    "c7i.xlarge": 0.202, "c7i-flex.xlarge": 0.162,
    "m7i.xlarge": 0.226, "m7i-flex.xlarge": 0.181,
    "r7i.xlarge": 0.298,
    # Intel 8th Gen
    "c8i.xlarge": 0.212, "c8i-flex.xlarge": 0.170,
    "m8i.xlarge": 0.237, "r8i.xlarge": 0.313, "r8i-flex.xlarge": 0.250,
    # Graviton2 (6g)
    "c6g.xlarge": 0.154, "c6gd.xlarge": 0.194, "c6gn.xlarge": 0.194,
    "m6g.xlarge": 0.172, "m6gd.xlarge": 0.206,
    "r6g.xlarge": 0.226, "r6gd.xlarge": 0.260,
    # Graviton3 (7g)
    "c7g.xlarge": 0.163, "c7gd.xlarge": 0.206,
    "m7g.xlarge": 0.183, "m7gd.xlarge": 0.226,
    "r7g.xlarge": 0.240, "r7gd.xlarge": 0.283,
    # Graviton4 (8g)
    "c8g.xlarge": 0.172, "m8g.xlarge": 0.193, "r8g.xlarge": 0.253,
}

def get_generation(instance):
    """Extract generation from instance type"""
    import re
    match = re.search(r'[cmr](\d+)', instance)
    return int(match.group(1)) if match else 0

def get_family(instance):
    """Extract family (c/m/r) from instance type"""
    return instance[0]

def is_graviton(instance):
    """Check if instance is Graviton (ARM)"""
    return 'g' in instance.split('.')[0]
