package oreilly.ch12;

import gov.nasa.jpf.awt.UIActionTree;
import gov.nasa.jpf.util.event.Event;

public class SimpleFileChooserTest extends UIActionTree {

  @Override
  public Event createEventTree() {
    return sequence(
      click("$Open", true)
    );
  }

}

