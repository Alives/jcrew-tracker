#!/usr/bin/env python
"""A web browser driver to interface with the external websites."""

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import httplib
import logging
import os
import socket
import signal
import urllib2


class ExceededRetries(Exception):
  """Error from retrying more than the given limit."""
  pass


class Browser(object):
  """The browser driver and supporting methods for interfacing with jcrew.com"""
  def __init__(self, user_agent):
    dcap = dict(DesiredCapabilities.PHANTOMJS)
    dcap["phantomjs.page.settings.userAgent"] = user_agent
    self.driver = webdriver.PhantomJS(
        desired_capabilities=dcap, service_args=['--ssl-protocol=any'],
        service_log_path=os.path.devnull)
    self.wait = WebDriverWait(self.driver, 10)
    self.driver.set_window_size(1120, 550)

  def get_attribute_data(self, tag, name):
    """Get a list of DOM elements that match the html tag and attribute name.

    Execute javascript that finds all DOM elements of the specified tag type and
    return all values of the matching attribute name if that attribute name
    exists.

    Example:  <div color="blue">
    Calling this function with ('div', 'color') would return ['blue'].

    Args:
        tag: (string) The html tag to search for.
        name: (string) The tag's attribute name feild to match on.

    Returns:
        A list of strings of the data from the name attributes.
    """
    logging.debug('Getting attributes for tag: %s name: %s', tag, name)
    for _ in xrange(3):
      try:
        return self.driver.execute_script("""
          var elements = document.getElementsByTagName("%s");
          var attribs = [];
          for (var i = 0; i < elements.length; i++) {
            item = elements[i].attributes.getNamedItem("%s");
            if (item) { attribs.push(item.nodeValue); }
          }
          return attribs;
          """ % (tag, name))
      except urllib2.URLError, e:
        logging.error('Error getting attributes for tag: %s name: %s', tag, name)
        continue
    logging.error('Couldn\'t get attributes for tag: %s name: %s', tag, name)
    exit(1)

  def get_price_map(self):
    """Get a map of color names to prices.

    Iterate over each color code and determine it's price, then return the map
    of color codes to prices.

    Returns: A dict of color name to price value.
    """
    logging.debug('Getting color names and prices.')
    return self.driver.execute_script("""
      var price_wrapper = document.getElementsByClassName('price-wrapper')[0];
      var color_divs = price_wrapper.getElementsByClassName('color-box');
      var prices = {};

      for (var i = 0; i < color_divs.length; i++) {
        if (! color_divs[i].classList.contains("unavailable")) {
          color = color_divs[i].firstElementChild.id;
          try {
            price = color_divs[i].parentNode.previousElementSibling.innerText;
          }
          catch(err) {
            price = "$-1.0";
          }
          prices[color] = price;
        }
      }
      return prices;
      """)

  def get_colors(self, size):
    """Get all color data that matches the desired size from the webpage.

    Execute javascript to get the values of all the available colors on the
    current page, as well as their prices, and codenames.

    Args:
        size: (string) The clothing size that is being queried.

    Returns:
        A dict with color codename keys and color names and prices as values.
    """
    colors = {}
    logging.info('Getting active colors')
    self.wait.until(EC.presence_of_element_located((By.ID, 'data-size')))
    self.driver.find_element_by_name(size.upper()).click()
    self.wait.until(EC.presence_of_element_located((By.CLASS_NAME, 'selected')))
    data = self.get_price_map()
    for color, price in data.iteritems():
      self.driver.find_element_by_name(color).click()
      name = self.get_node_text('color-name').title().strip()
      price = float(price.split('$')[-1])
      if price == -1.0:
        price = float(self.get_node_text('full-price').split('$')[-1])
      colors[color] = {'name': name, 'price': price, 'active': True}
    return colors

  def get_node_text(self, class_name):
    """Get values from elements with matching class-names' children.

    Args:
        class_name: (string) The class name to match.

    Returns:
        A string from the first matching class and first child node's value.
    """
    logging.debug('Getting node text for class %s', class_name)
    return self.driver.execute_script(
        ('return document.getElementsByClassName("%s")[0]'
         '.childNodes[0].nodeValue') % class_name)

  def check_size(self, size):
    """Make sure the desired size is available and exit if not.

    Args:
        size: (string) The clothing size that is being queried.
    """
    logging.info('Getting current sizes')
    sizes = self.get_attribute_data('div', 'data-size')
    if size not in [x.lower() for x in sizes]:
      logging.error('%s is not currently available: %s', size, str(sizes))
      exit(1)
    logging.info('Size %s is currently available.', size)

  def get_url(self, url, tries=4):
    """Load the url with the browser object and wait for loading to finish.

    Args:
        tries: (int) The number of allowed retries.
    """
    logging.info('Loading %s', url)
    for i in xrange(tries):
      try:
        self.driver.get(url)
        self.wait.until(
            EC.presence_of_element_located((By.CLASS_NAME, 'color-box')))
        return
      except TimeoutException:
        logging.error('Timeout trying to get %s. %d of %d tries.',
                      url, i, tries)
        continue
      except httplib.BadStatusLine:
        logging.error('Bad status line trying to get %s. %d of %d tries.',
                      url, i, tries)
        continue
      except (socket.error, urllib2.URLError), e:
        logging.error('Error opening url: %s', e)
        continue
      raise ExceededRetries('Failed to get the resource in %d tries' % tries)

  def quit(self):
    """Quit the browser session."""
    # https://github.com/seleniumhq/selenium/issues/767
    self.driver.service.process.send_signal(signal.SIGTERM)
    self.driver.quit()

  def update_divs(self):
    """Add attributes to div tags with data from other attributes in the tag.

    Update any div that has an attribute named 'data-size' or 'data-color' by
    adding new name and id attributes since they shouldn't already exist.  The
    name attribute is the value of the 'data-size' or 'data-color' attribute
    and the id attribute is either 'data-size' or 'data-color'.
    """
    logging.info('Updating data-size and data-color divs')
    self.driver.execute_script('''
      var attribs;
      var allDivs = document.getElementsByTagName("div");
      var ids = ["data-size", "data-color"];
      var item;
      for (var i = 0; i < allDivs.length; i++) {
        attribs = allDivs[i].attributes;
        for (var j = 0; j <= 1; j++) {
          item = attribs.getNamedItem(ids[j]);
          if (item) {
            allDivs[i].setAttribute("id", ids[j]);
            allDivs[i].setAttribute("name", item.nodeValue);
          }
        }
      }''')
