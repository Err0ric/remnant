### Development: the publish scan catches more real-looking names (2026-11-12)

- Development tooling only (`scripts/publish/`, not part of the public tree). The scan that stops a publish when the tree names a real organization missed some forms (found by the 2026-11 audit): names in capitals, names in code comments, some country and business endings, a customer's own subdomain under an allowed vendor (a Slack workspace, a Microsoft tenant), links to another owner's repositories, names in a file's own name, and images, which it could not read at all.
- It now reads names in any letter case and in comments, knows more endings, allows tenant-bearing vendors by exact host only, checks the owner in repository links against a list, scans file names, and stops on an image (or any file that is not text) that is not in the reviewed list `scripts/publish/binaries.txt`. The leak scan also knows the shape of a real Slack webhook path and a signed webhook URL.
- The images already in the tree are listed as they were; they were not looked at again.
- What you will notice: nothing visible.
- What changes for existing installs: nothing.
