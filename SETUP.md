# ShatterStop Video Bot: Setup

Three times a day the bot takes the next product from your store, makes a 15 to 25 second video and posts it on the ShatterStop Facebook Page. Posts alternate between English and Spanish.

It runs on GitHub's free servers, so your computer does not need to be on. It posts through Make.com's official Facebook connection, so it never logs in as you.

## What it does on every run
1. **Pulls the products.** It reads the live product list from the store. New products join the rotation automatically, and sold out ones drop out.
2. **Picks the next product.** It goes through the whole catalog in a shuffled order, so nothing repeats until every product has posted.
3. **Writes the script.** All 20 current products have scripts written from their real specs, in both languages. A product added later gets a basic script made from its title and category.
4. **Renders the video.** It uses the clean dark style: hook, product reveal on the beat drop, three feature callouts, price, then the AstraPoint end card. It uses your real product photos, a natural voice and fresh music for each video.
5. **Posts it.** It posts the video with a caption that has the hook, the price, a Greenville line and a tracked link.

## Easiest way: the setup page
Double-click **ShatterStop Bot Setup** on your Desktop. It walks you through everything with buttons and copy buttons. No Meta developer account is needed.

## How the posting works
GitHub makes the video and hosts it. It then sends the video link and caption to a Make.com scenario. Make posts it to the ShatterStop Page through its normal "Log in with Facebook" connection. Make's free plan covers 3 posts a day.

## Steps (the same as the setup page)
1. **GitHub:** make a public repo named `shatterstop-bot`, upload these files, and add the schedule file at `.github/workflows/post.yml`.
2. **Make.com:** sign up free.
3. **Webhook:** in a new scenario, add a Webhooks > Custom webhook block and copy its address.
4. **Posting blocks:** add these three blocks after the webhook:
   * HTTP > Get a file, with URL `{{1.video_url}}`.
   * Facebook Pages > Upload a Video. Pick ShatterStop as the Page, the HTTP file as the file, and `{{1.short}}` as the description.
   * Facebook Pages > Update a Video, with Video ID `{{3.id}}` and description `{{1.caption}}`.

   Save the scenario and turn it ON.
5. **Secret:** in GitHub, add a secret named `MAKE_WEBHOOK_URL` with the webhook address.
6. **Test:** go to Actions, then Run workflow. A dry run only renders. A normal run posts.

## Discount codes
Videos only mention a code when it is real and switched on in `codes.json`. GVILLE10 for the dash cam is in there but switched off (`"active": false`), because the code doesn't exist in Shopify yet. Once it exists, change it to `true` (edit the file right on GitHub). After Oct 31 it stops showing on its own.

## Changing things later
* **Script for a product:** edit `scripts.json`. Each product has `hook`, `say` and three `chips` in `en` and `es`.
* **Posts per day:** change the three `cron` lines in `.github/workflows/post.yml`.
* **Language:** add `LANG_MODE: both` under `env` in the workflow to post both languages each time, or `en` or `es` for one only.
* **TikTok:** not hooked up yet. The videos are already TikTok size, so it can be added later.
