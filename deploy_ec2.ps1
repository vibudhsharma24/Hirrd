# deploy_ec2.ps1
# Automates the deployment of IITIIM Job Assistant to AWS EC2

$IP = "3.110.197.3"
$User = "ubuntu"
$Key = "iitiim-key.pem"
$RemoteDir = "/home/ubuntu/iitiim"

Write-Host "1. Creating local archive (app.tar.gz)..." -ForegroundColor Cyan
if (Test-Path app.tar.gz) { Remove-Item app.tar.gz -Force }

# Create tarball using local bsdtar
tar -czf app.tar.gz core frontend job_seeker_agent naukri_agent requirements.txt run.py linkedin-cookies.json linkedin-config.yml

Write-Host "2. Backing up existing database on EC2..." -ForegroundColor Cyan
ssh -n -i $Key -o StrictHostKeyChecking=no "${User}@${IP}" 'mkdir -p /home/ubuntu/iitiim_backups && TS=$(date +%Y%m%d%H%M%S) && [ -f /home/ubuntu/iitiim/users.db ] && cp /home/ubuntu/iitiim/users.db /home/ubuntu/iitiim_backups/users.db.bak.$TS || true && [ -f /home/ubuntu/iitiim/jobs.db ] && cp /home/ubuntu/iitiim/jobs.db /home/ubuntu/iitiim_backups/jobs.db.bak.$TS || true'

Write-Host "3. Uploading app.tar.gz to EC2..." -ForegroundColor Cyan
$remoteDest = "${User}@${IP}:/home/ubuntu/app.tar.gz"
scp -i $Key -o StrictHostKeyChecking=no app.tar.gz $remoteDest

Write-Host "4. Extracting app.tar.gz on EC2..." -ForegroundColor Cyan
ssh -n -i $Key -o StrictHostKeyChecking=no "$User`@$IP" "tar -xzf /home/ubuntu/app.tar.gz -C $RemoteDir"

Write-Host "5. Configuring production .env on EC2..." -ForegroundColor Cyan
# Read local .env and replace local redirect URI with production redirect URI
$envContent = Get-Content .env -Raw
$envContent = $envContent -replace 'GOOGLE_REDIRECT_URI=http://localhost:5000/auth/google/callback', 'GOOGLE_REDIRECT_URI=https://iitiimjobassistant.in/auth/google/callback'
$envContent | Out-File -FilePath .env.production -Encoding utf8 -Force

# Upload the production .env file
$remoteEnvDest = "${User}@${IP}:${RemoteDir}/.env"
scp -i $Key -o StrictHostKeyChecking=no .env.production $remoteEnvDest
Remove-Item .env.production -Force

Write-Host "6. Installing Python dependencies in virtual environment..." -ForegroundColor Cyan
ssh -n -i $Key -o StrictHostKeyChecking=no "$User`@$IP" "$RemoteDir/venv/bin/pip install --upgrade pip && $RemoteDir/venv/bin/pip install -r $RemoteDir/requirements.txt gunicorn"

Write-Host "7. Installing Playwright browsers and dependencies on EC2..." -ForegroundColor Cyan
ssh -n -i $Key -o StrictHostKeyChecking=no "$User`@$IP" "sudo DEBIAN_FRONTEND=noninteractive apt-get update && $RemoteDir/venv/bin/playwright install --with-deps"

Write-Host "8. Updating systemd service configuration..." -ForegroundColor Cyan
$ServiceFileContent = @"
[Unit]
Description=IITIIM Flask App
After=network.target

[Service]
User=ubuntu
WorkingDirectory=$RemoteDir

EnvironmentFile=$RemoteDir/.env
Environment="PATH=$RemoteDir/venv/bin"

ExecStart=$RemoteDir/venv/bin/gunicorn --workers 3 --bind 127.0.0.1:5000 run:app

[Install]
WantedBy=multi-user.target
"@

$ServiceFileContent | Out-File -FilePath iitiim.service.temp -Encoding utf8 -Force
$remoteServiceDest = "${User}@${IP}:/home/ubuntu/iitiim.service"
scp -i $Key -o StrictHostKeyChecking=no iitiim.service.temp $remoteServiceDest
Remove-Item iitiim.service.temp -Force

# Move service file to systemd and reload
ssh -n -i $Key -o StrictHostKeyChecking=no "$User`@$IP" "sudo mv /home/ubuntu/iitiim.service /etc/systemd/system/iitiim.service && sudo systemctl daemon-reload && sudo systemctl restart iitiim && sudo systemctl enable iitiim"

Write-Host "9. Cleaning up temporary archive files..." -ForegroundColor Cyan
Remove-Item app.tar.gz -Force
ssh -n -i $Key -o StrictHostKeyChecking=no "$User`@$IP" "rm -f /home/ubuntu/app.tar.gz"

Write-Host "Deployment completed successfully!" -ForegroundColor Green
