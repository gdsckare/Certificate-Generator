# GDG KARE Certificate Generator

A fast, privacy-friendly certificate generator built for clubs and chapters at Kalasalingam Academy of Research and Education (KARE). Many student clubs at KARE used to manually create certificates; this tool automates the process and standardizes appearance. It was developed as an internal tool for GDG on Campus KARE and is now open-sourced. Contributions are welcome.

## Why this project?
- Many clubs manually generate certificates → slow and error-prone
- Need a consistent look-and-feel across events and teams
- Self-hosted and privacy-conscious: files are not persisted; outputs are auto-cleaned

## Key features
- Upload your data file (`.csv` or `.xlsx`) and a base certificate image
- Interactive placement of multiple columns onto the image with per-column font sizes
- Live preview (streamed, not saved to disk)
- Async generation with progress indicator (completed/total) on the same “Generate” button
- One-click ZIP download of all generated images
- Automatic cleanup
  - Outputs removed after download
  - Auto-delete outputs and uploads after inactivity (default 10 minutes)
- Font selection
  - Choose from bundled fonts or upload a `.ttf` (“Other”) to add it for everyone
- Dark UI and GDG-styled header with a quick link to the source repo

## Tech stack
- Backend: Flask, Pillow (PIL), Pandas, OpenPyXL
- Frontend: HTML/CSS/JS (vanilla)

## Getting started
1. Requirements
   - Python 3.10+
   - Pip packages:
     ```bash
     pip install flask pandas pillow openpyxl
     ```
2. Run the app
   ```bash
   python app/app.py
   ```
3. Open the app: http://localhost:5000

## Usage
1. Upload your data file (`.csv`/`.xlsx`) and base certificate image
2. Configure positions for each column and set font sizes
3. Optional: choose a font (or pick “Other” to upload a `.ttf”)
4. Preview to validate layout
5. Click Generate; the button shows generating progress and turns into Download
6. Download the ZIP; outputs are deleted server-side after download

## Data handling and privacy
- Previews are generated in-memory and never written to disk
- Generated outputs are deleted immediately after download
- A background janitor deletes any leftover job outputs and uploads after a timeout (default 10 minutes)
- Uploaded custom fonts are stored to make them available to all users of the instance

## Configuration
You can customize branding, links, and cleanup timing with environment variables:
- `GDG_NAME` (default: "GDG On Campus KARE")
- `GITHUB_URL` (link shown in the header; default: `https://github.com/gdsckare/Certificate-Generator`)
- `CONTRIBUTOR_GITHUB` (default: `https://github.com/bharath-inukurthi`)
- `LINKEDIN_URL` (default: `https://www.linkedin.com/in/bharath-kumar-inukurthi`)
- `CONTACT_EMAIL` (default: `bharathinukurthi1@gmail.com`)
- `JOB_TTL_SECONDS` (default: `600`, auto-delete after done)
- `JOB_STALE_SECONDS` (default: `3600`, cleanup stale running jobs)

## Contributing
Contributions are welcome! Please:
- Fork the repo and create a feature branch
- Keep changes focused and follow clear commit messages
- Add sensible defaults and avoid breaking flows
- Open a pull request describing your changes and testing done

Source repository and developer profile:
- Source: `https://github.com/gdsckare/Certificate-Generator`
- Author: `https://github.com/bharath-inukurthi`

## Acknowledgments
- Built with ❤️ by Inukurthi Bharath Kumar ,Open Source Contributor at GDG on Campus KARE

## Links
- GitHub (source): `https://github.com/gdsckare/Certificate-Generator`
- GitHub (author): `https://github.com/bharath-inukurthi`
- LinkedIn: `https://www.linkedin.com/in/bharath-kumar-inukurthi`
- Email: `bharathinukurthi1@gmail.com`


